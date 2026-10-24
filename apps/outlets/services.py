"""Outlet (restaurant, bar, spa…) business rules."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import BusinessError
from apps.core.models import audit
from apps.finance.models import Charge, Folio, Payment
from apps.frontdesk.models import Reservation

from .models import Item, KitchenTicket, Order, OrderLine, Outlet, Table


def _require_open(order: Order) -> None:
    if order.status != Order.Status.OPEN:
        raise BusinessError(_("This order is already closed."))


def open_order(outlet: Outlet, *, user, table: Table | None = None, guests: int = 1, label: str = "") -> Order:
    if not outlet.is_active:
        raise BusinessError(_("This outlet is closed."))
    if table is not None:
        if table.outlet_id != outlet.pk:
            raise BusinessError(_("That table belongs to another outlet."))
        existing = table.open_order()
        if existing:
            return existing
    try:
        with transaction.atomic():
            order = Order.objects.create(outlet=outlet, table=table, guests=max(1, guests), label=label, opened_by=user)
    except IntegrityError:
        # Someone opened the same table a moment ago: use their order.
        return table.open_order()
    audit(user, "order.open", f"{outlet} {order.display_name}", order)
    return order


@transaction.atomic
def add_item(
    order: Order, item: Item, *, user, quantity: int = 1, note: str = "", option_ids: list | None = None
) -> OrderLine:
    from .pricing import adjust, rule_for

    order = Order.objects.select_for_update().get(pk=order.pk)
    _require_open(order)
    item = Item.objects.select_related("category__station").get(pk=item.pk)
    if item.category.outlet_id != order.outlet_id:
        raise BusinessError(_("That item is not sold here."))
    if not item.is_active:
        raise BusinessError(_("%(item)s is not available.") % {"item": item.name})
    chosen = _chosen_options(item, option_ids or [])
    rule = rule_for(item)
    unit_price = adjust(item.price + sum((o.price_change for o in chosen), Decimal("0")), rule)
    name = item.name
    if chosen:
        name = f"{item.name} · {', '.join(o.name for o in chosen)}"[:120]
    station = item.category.station if item.category.station_id and item.category.station.is_active else None
    status = OrderLine.Status.NEW if station else OrderLine.Status.DIRECT
    if not note:
        # Only merge into lines the kitchen hasn't seen yet, with the same choices and price.
        line = order.lines.filter(
            item=item, name=name, note="", unit_price=unit_price, status=status, quantity__gt=0
        ).first()
        if line:
            line.quantity += max(1, quantity)
            line.save(update_fields=["quantity"])
            return line
    return OrderLine.objects.create(
        order=order,
        item=item,
        name=name,
        unit_price=unit_price,
        quantity=max(1, quantity),
        note=note,
        options=[{"id": o.pk, "name": o.name, "price": str(o.price_change)} for o in chosen],
        price_note=rule.label[:60] if rule else "",
        station=station,
        status=status,
        added_by=user,
    )


def _chosen_options(item: Item, option_ids: list) -> list:
    """Check the choices against the item's option groups: one per group unless several are allowed,
    and every required group answered."""
    from .models import Option

    groups = list(item.option_groups.prefetch_related("options"))
    if not groups:
        return []
    try:
        ids = {int(x) for x in option_ids if str(x).strip()}
    except ValueError:
        raise BusinessError(_("Unknown option."))
    valid = {o.pk: o for g in groups for o in g.options.all() if o.is_active}
    if ids - set(valid):
        raise BusinessError(_("Unknown option."))
    chosen: list[Option] = []
    for g in groups:
        picked = [valid[i] for i in sorted(ids) if valid[i].group_id == g.pk]
        if g.required and not picked:
            raise BusinessError(_("Choose %(group)s for %(item)s.") % {"group": g.name.lower(), "item": item.name})
        if not g.multiple and len(picked) > 1:
            raise BusinessError(_("Choose only one %(group)s.") % {"group": g.name.lower()})
        chosen += sorted(picked, key=lambda o: (o.sort_order, o.pk))
    return chosen


@transaction.atomic
def change_quantity(line: OrderLine, delta: int, *, user) -> OrderLine | None:
    line = OrderLine.objects.select_for_update().select_related("order", "item").get(pk=line.pk)
    order = line.order
    _require_open(order)
    if delta > 0 and line.status == OrderLine.Status.SENT:
        # The kitchen already has this one: more of it is a new item to send.
        if line.item_id is None:
            raise BusinessError(_("This item is no longer on the menu."))
        return add_item(
            order, line.item, user=user, quantity=delta, note=line.note, option_ids=[o["id"] for o in line.options]
        )
    if delta > 0 and line.item_id and not line.item.is_active:
        raise BusinessError(_("%(item)s is sold out.") % {"item": line.name})
    new_qty = line.quantity + delta
    if delta < 0 and order.total - line.unit_price * min(-delta, line.quantity) < order.paid:
        raise BusinessError(_("Part of this bill is already paid. Void the payment before removing items."))
    if line.status == OrderLine.Status.SENT:
        # Keep the line so the kitchen screen can show what was taken off.
        line.quantity = max(new_qty, 0)
        line.save(update_fields=["quantity"])
        audit(user, "order.line_reduced", f"#{order.number}: {line.name} {line.sent_quantity}→{line.quantity}", order)
        if line.ticket_id:
            ticket = line.ticket
            if not ticket.lines.filter(quantity__gt=0).exists() and ticket.status in KitchenTicket.ON_BOARD:
                ticket.status = KitchenTicket.Status.CANCELLED
                ticket.save(update_fields=["status"])
        _fit_discount(order, user)
        return line if line.quantity else None
    if new_qty <= 0:
        audit(user, "order.line_removed", f"#{order.number}: {line}", order)
        line.delete()
        _fit_discount(order, user)
        return None
    line.quantity = new_qty
    line.save(update_fields=["quantity"])
    if delta < 0:
        _fit_discount(order, user)
    return line


def _fit_discount(order: Order, user) -> None:
    """After items are taken off, keep the discount within the bill and (for staff) within their limit."""
    from apps.core.models import HotelSettings

    if not order.discount:
        return
    order = Order.objects.get(pk=order.pk)
    subtotal = order.subtotal
    allowed = subtotal
    if not getattr(user, "is_manager", False):
        limit = HotelSettings.load().max_staff_discount
        allowed = min(allowed, (subtotal * limit / Decimal("100")).quantize(Decimal("0.01")))
    if order.discount > allowed:
        audit(user, "order.discount", _("#%(n)s: %(d)s → %(a)s (items removed)") % {"n": order.number, "d": order.discount, "a": allowed}, order)
        order.discount = allowed
        if not allowed:
            order.discount_reason = ""
        order.save(update_fields=["discount", "discount_reason"])


def send_to_kitchen(order: Order, *, user) -> list[KitchenTicket]:
    """Send every new item to its station: one ticket per station, printed if the station has a printer."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        new_lines = list(order.lines.filter(status=OrderLine.Status.NEW, quantity__gt=0).select_related("station"))
        by_station: dict[int, list[OrderLine]] = {}
        for line in new_lines:
            by_station.setdefault(line.station_id, []).append(line)
        tickets = []
        for station_id, lines in by_station.items():
            ticket = KitchenTicket.objects.create(order=order, station_id=station_id, sent_by=user)
            for line in lines:
                line.status, line.ticket, line.sent_quantity = OrderLine.Status.SENT, ticket, line.quantity
                line.save(update_fields=["status", "ticket", "sent_quantity"])
            tickets.append(ticket)
        if tickets:
            audit(user, "order.sent", _("#%(n)s: %(c)s item(s) sent") % {"n": order.number, "c": sum(len(v) for v in by_station.values())}, order)
    for ticket in tickets:
        # Print only once the order is safely saved (and never while holding database locks).
        transaction.on_commit(lambda t=ticket: _print_ticket(t, user))
    return tickets


def _print_ticket(ticket: KitchenTicket, user) -> None:
    from . import printing

    station = ticket.station
    if station.printer_id and station.printer.is_active:
        ticket.print_job = printing.submit(
            station.printer,
            f"{station.name}: {ticket.order.display_name}",
            printing.kitchen_document(ticket, station.printer),
            user,
        )


def set_ticket_status(ticket: KitchenTicket, status: str, *, user) -> KitchenTicket:
    now = timezone.now()
    if status not in KitchenTicket.Status.values:
        raise BusinessError(_("Unknown status."))
    ticket = KitchenTicket.objects.get(pk=ticket.pk)  # the screen may be a few seconds old
    if ticket.status in (KitchenTicket.Status.CANCELLED, KitchenTicket.Status.SERVED) and status != KitchenTicket.Status.SERVED:
        return ticket  # a cancelled or served ticket can only be cleared, never brought back
    ticket.status = status
    fields = ["status"]
    if status == KitchenTicket.Status.PREPARING and not ticket.started_at:
        ticket.started_at = now
        fields.append("started_at")
    if status == KitchenTicket.Status.READY:
        ticket.ready_at = now
        fields.append("ready_at")
    if status == KitchenTicket.Status.SERVED:
        ticket.served_at = now
        fields.append("served_at")
    ticket.save(update_fields=fields)
    return ticket


@transaction.atomic
def set_discount(
    order: Order, *, user, amount: Decimal | None = None, percent: Decimal | None = None, reason: str = ""
) -> Order:
    """Give a discount by amount or percent. Service staff are limited by Settings → max discount."""
    from apps.core.models import HotelSettings

    order = Order.objects.select_for_update().get(pk=order.pk)
    _require_open(order)
    subtotal = order.subtotal
    if percent is not None:
        amount = (subtotal * percent / Decimal("100")).quantize(Decimal("0.01"))
    amount = (amount or Decimal("0")).quantize(Decimal("0.01"))
    if amount < 0 or amount > subtotal:
        raise BusinessError(_("The discount must be between 0 and the bill total."))
    if not user.is_manager and amount > 0:
        limit = HotelSettings.load().max_staff_discount
        if limit == 0 or (subtotal and amount * 100 / subtotal > limit):
            raise BusinessError(_("Discounts above %(p)s%% need a manager.") % {"p": limit})
    if subtotal - amount < order.paid:
        raise BusinessError(_("Part of this bill is already paid. The total cannot go below the amount paid."))
    if amount > 0 and not reason.strip():
        raise BusinessError(_("Give a reason for the discount."))
    order.discount = amount
    order.discount_reason = reason.strip()[:120] if amount else ""
    order.save(update_fields=["discount", "discount_reason"])
    audit(user, "order.discount", f"#{order.number}: {amount} ({order.discount_reason})", order)
    return order


@transaction.atomic
def pay_order(
    order: Order,
    *,
    method: str,
    user,
    amount: Decimal | None = None,
    tendered: Decimal | None = None,
    reference: str = "",
    tip: Decimal | None = None,
    voucher_code: str = "",
    foreign: dict | None = None,
) -> Payment:
    """Take a full or partial payment. The order closes when nothing is left to pay.

    For cash, `tendered` is what the customer handed over; the change is shown on the receipt.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require_open(order)
    if order.total <= 0 and order.subtotal > 0 and not order.payments.filter(voided=False).exists():
        # Fully discounted (staff meal, on the house): close it without money, so it is on record
        # with its discount and the stock is taken.
        Charge.objects.create(
            order=order,
            outlet=order.outlet,
            kind=Charge.Kind.OUTLET,
            description=f"{order.outlet} – {order.display_name}",
            quantity=1,
            unit_price=Decimal("0"),
            created_by=user,
        )
        _close(order, Order.Settlement.PAID, user)
        return None
    if order.total <= 0:
        raise BusinessError(_("The order is empty."))
    remaining = order.remaining
    voucher = None
    if method == Payment.Method.VOUCHER:
        from apps.finance import loyalty

        voucher = loyalty.find_voucher(voucher_code, lock=True)
        if amount is None:
            amount = min(remaining, max(voucher.balance, Decimal("0")))
            if amount <= 0:
                loyalty.check_spend(voucher, Decimal("0.01"))  # explains why (used up, expired, voided)
    if amount is None:
        amount = remaining
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount <= 0:
        raise BusinessError(_("Enter an amount."))
    if amount > remaining:
        raise BusinessError(_("Only %(left)s is left to pay.") % {"left": f"{remaining:.2f}"})
    if foreign:
        if method != Payment.Method.CASH:
            raise BusinessError(_("Only cash can be taken in another currency."))
        from apps.finance.currency import drop_odd_change

        foreign = drop_odd_change(foreign, amount)
        tendered = foreign["tendered"]
    if tendered is not None:
        tendered = Decimal(tendered).quantize(Decimal("0.01"))
        if method != Payment.Method.CASH:
            tendered = None
        elif tendered < amount:
            raise BusinessError(_("The cash given is less than the amount."))
    tip = Decimal(tip or 0).quantize(Decimal("0.01"))
    if tip < 0:
        raise BusinessError(_("The tip can't be negative."))
    if tendered is not None and tip > tendered - amount:
        raise BusinessError(_("The tip can't be more than the change."))
    if voucher is not None:
        loyalty.check_spend(voucher, amount)
        reference, tip, tendered = voucher.code, Decimal("0"), None
    payment = Payment.objects.create(
        order=order,
        amount=amount,
        method=method,
        reference=reference,
        tendered=tendered,
        tip=tip,
        voucher=voucher,
        created_by=user,
        **({k: v for k, v in foreign.items() if k != "tendered"} if foreign else {}),
    )
    audit(user, "order.payment", f"{order.outlet} #{order.number} {amount} ({Payment.Method(method).label if method in Payment.Method.values else method})", order)
    if order.remaining <= 0:
        Charge.objects.create(
            order=order,
            outlet=order.outlet,
            kind=Charge.Kind.OUTLET,
            description=f"{order.outlet} – {order.display_name}",
            quantity=1,
            unit_price=order.total,
            created_by=user,
        )
        _close(order, Order.Settlement.PAID, user)
    return payment


@transaction.atomic
def charge_to_room(order: Order, reservation: Reservation, *, user) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require_open(order)
    if order.total <= 0:
        raise BusinessError(_("The order is empty."))
    if reservation.status != Reservation.Status.CHECKED_IN:
        raise BusinessError(_("Only in-house guests can charge to their room."))
    folio, _created = Folio.objects.select_for_update().get_or_create(reservation=reservation)
    if folio.status != Folio.Status.OPEN:
        raise BusinessError(_("This guest's bill is closed."))
    paid, remaining = order.paid, order.remaining
    if paid > 0:  # part already paid at the table: that part is ordinary outlet revenue
        Charge.objects.create(
            order=order,
            outlet=order.outlet,
            kind=Charge.Kind.OUTLET,
            description=f"{order.outlet} – {order.display_name}",
            quantity=1,
            unit_price=paid,
            created_by=user,
        )
    Charge.objects.create(
        folio=folio,
        order=order,
        outlet=order.outlet,
        kind=Charge.Kind.OUTLET,
        description=f"{order.outlet} – #{order.number}",
        quantity=1,
        unit_price=remaining,
        created_by=user,
    )
    _close(order, Order.Settlement.ROOM, user)
    if paid > 0:  # the part paid at the table gets its own fiscal receipt
        from apps.fiscal import services as fiscal

        transaction.on_commit(lambda: fiscal.safely(fiscal.fiscalize_order, order, user))
    audit(user, "order.room_charge", f"{order.outlet} #{order.number} {remaining} → {reservation.room.number}", order)
    return order


@transaction.atomic
def charge_to_account(order: Order, account, *, user) -> Order:
    """Put what is left of the bill on a regular's account (their tab), to be paid later."""
    from apps.finance.models import CustomerAccount

    order = Order.objects.select_for_update().get(pk=order.pk)
    _require_open(order)
    if order.total <= 0:
        raise BusinessError(_("The order is empty."))
    account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
    if not account.is_active:
        raise BusinessError(_("This account is closed."))
    paid, remaining = order.paid, order.remaining
    balance = account.balance
    if account.credit_limit is not None and balance + remaining > account.credit_limit and not user.is_manager:
        raise BusinessError(
            _("This would take %(name)s over the credit limit of %(limit)s (owes %(balance)s now). A manager can allow it.")
            % {"name": account.name, "limit": f"{account.credit_limit:.2f}", "balance": f"{balance:.2f}"}
        )
    if paid > 0:  # part already paid at the table
        Charge.objects.create(
            order=order,
            outlet=order.outlet,
            kind=Charge.Kind.OUTLET,
            description=f"{order.outlet} – {order.display_name}",
            quantity=1,
            unit_price=paid,
            created_by=user,
        )
    Charge.objects.create(
        account=account,
        order=order,
        outlet=order.outlet,
        kind=Charge.Kind.OUTLET,
        description=f"{order.outlet} – #{order.number}",
        quantity=1,
        unit_price=remaining,
        created_by=user,
    )
    _close(order, Order.Settlement.ACCOUNT, user)
    audit(user, "order.account", f"{order.outlet} #{order.number} {remaining} → {account.name}", order)
    return order


@transaction.atomic
def move_order(order: Order, table: Table, *, user) -> Order:
    """Move an order to a free table, or merge it into the order already on that table."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require_open(order)
    if table.outlet_id != order.outlet_id:
        raise BusinessError(_("That table belongs to another outlet."))
    if table.pk == order.table_id:
        return order
    target = table.orders.select_for_update().filter(status=Order.Status.OPEN).first()
    if target is None:
        old = order.table.name if order.table_id else order.display_name
        order.table = table
        order.save(update_fields=["table"])
        audit(user, "order.move", f"#{order.number}: {old} → {table.name}", order)
        return order
    if order.payments.filter(voided=False).exists():
        raise BusinessError(_("This bill has payments, so it can't be merged. Move it to a free table instead."))
    order.lines.update(order=target)
    order.tickets.update(order=target)
    target.guests += order.guests
    target.note = " · ".join(n for n in (target.note, order.note) if n)[:255]
    if order.discount:
        target.discount += order.discount
        target.discount_reason = " · ".join(x for x in (target.discount_reason, order.discount_reason) if x)[:120]
    target.save(update_fields=["guests", "note", "discount", "discount_reason"])
    order.status = Order.Status.CANCELLED
    order.note = (_("Merged into #%(n)s") % {"n": target.number})[:255]
    order.closed_at = timezone.now()
    order.closed_by = user
    order.save(update_fields=["status", "note", "closed_at", "closed_by"])
    audit(user, "order.merge", f"#{order.number} → #{target.number} ({table.name})", target)
    return target


@transaction.atomic
def cancel_order(order: Order, *, user) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require_open(order)
    if order.lines.filter(Q(quantity__gt=0) | Q(sent_quantity__gt=0)).exists() and not user.is_manager:
        # Also when the items sent to the kitchen were taken off first.
        raise BusinessError(_("Only a manager can cancel an order that has items."))
    if order.payments.filter(voided=False).exists():
        raise BusinessError(_("This bill has payments. Void them first."))
    order.status = Order.Status.CANCELLED
    order.closed_at = timezone.now()
    order.closed_by = user
    order.save(update_fields=["status", "closed_at", "closed_by"])
    order.tickets.filter(status__in=[KitchenTicket.Status.NEW, KitchenTicket.Status.PREPARING]).update(
        status=KitchenTicket.Status.CANCELLED
    )
    audit(user, "order.cancel", f"{order.outlet} #{order.number} {order.total}", order)
    return order


@transaction.atomic
def void_payment(payment: Payment, *, user, reason: str) -> None:
    """Undo a payment taken by mistake on a bill that is still open."""
    if not user.is_manager:
        raise BusinessError(_("Only a manager can void entries."))
    if not reason.strip():
        raise BusinessError(_("Give a reason for the void."))
    payment = Payment.objects.select_for_update().select_related("order").get(pk=payment.pk)
    _require_open(payment.order)
    payment.voided, payment.void_reason, payment.voided_by, payment.voided_at = True, reason[:255], user, timezone.now()
    payment.save(update_fields=["voided", "void_reason", "voided_by", "voided_at"])
    audit(user, "payment.void", f"#{payment.order.number} {payment.amount} – {reason}", payment.order)


@transaction.atomic
def void_receipt(order: Order, *, user, reason: str) -> Order:
    """Cancel a closed bill (e.g. wrong items). Reverses its revenue and payments. Managers only."""
    if not user.is_manager:
        raise BusinessError(_("Only a manager can void entries."))
    if not reason.strip():
        raise BusinessError(_("Give a reason for the void."))
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != Order.Status.CLOSED:
        raise BusinessError(_("Only closed bills can be voided."))
    now = timezone.now()
    for charge in order.charges.filter(voided=False).select_related("folio"):
        if charge.folio_id and charge.folio.status != Folio.Status.OPEN:
            raise BusinessError(_("This was charged to a guest bill that is already closed."))
        charge.voided, charge.void_reason, charge.voided_by, charge.voided_at = True, reason[:255], user, now
        charge.save(update_fields=["voided", "void_reason", "voided_by", "voided_at"])
    order.payments.filter(voided=False).update(voided=True, void_reason=reason[:255], voided_by=user, voided_at=now)
    order.status = Order.Status.CANCELLED
    order.note = (_("Voided: %(r)s") % {"r": reason})[:255]
    order.save(update_fields=["status", "note"])
    from apps.inventory.services import return_for_order

    return_for_order(order, user)
    from apps.finance.loyalty import on_order_voided

    on_order_voided(order)
    from apps.fiscal import services as fiscal

    transaction.on_commit(lambda: fiscal.safely(fiscal.correct_order, order, user))
    audit(user, "order.void", f"{order.outlet} #{order.number} {order.total} – {reason}", order)
    return order


def _close(order: Order, settlement: str, user) -> None:
    from apps.core.models import Sequence

    send_to_kitchen(order, user=user)  # anything not sent yet still has to be prepared

    order.status = Order.Status.CLOSED
    order.settlement = settlement
    order.closed_at = timezone.now()
    order.closed_by = user
    order.receipt_number = Sequence.next("receipt", timezone.localdate().year)
    order.save(update_fields=["status", "settlement", "closed_at", "closed_by", "receipt_number"])
    from apps.finance.loyalty import on_order_closed

    on_order_closed(order)
    from apps.inventory.services import consume_for_order

    consume_for_order(order, user)
    if settlement in (Order.Settlement.PAID, Order.Settlement.ACCOUNT):  # a sale on account is fiscalized now
        from apps.fiscal import services as fiscal

        transaction.on_commit(lambda: fiscal.safely(fiscal.fiscalize_order, order, user))
