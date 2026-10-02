"""Outlet (restaurant, bar, spa…) business rules."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import BusinessError
from apps.core.models import audit
from apps.finance.models import Charge, Folio, Payment
from apps.frontdesk.models import Reservation

from .models import Item, Order, OrderLine, Outlet, Table


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
def add_item(order: Order, item: Item, *, user, quantity: int = 1, note: str = "") -> OrderLine:
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require_open(order)
    if item.category.outlet_id != order.outlet_id:
        raise BusinessError(_("That item is not sold here."))
    if not item.is_active:
        raise BusinessError(_("%(item)s is not available.") % {"item": item.name})
    if not note:
        line = order.lines.filter(item=item, note="", unit_price=item.price).first()
        if line:
            line.quantity += max(1, quantity)
            line.save(update_fields=["quantity"])
            return line
    return OrderLine.objects.create(
        order=order,
        item=item,
        name=item.name,
        unit_price=item.price,
        quantity=max(1, quantity),
        note=note,
        added_by=user,
    )


@transaction.atomic
def change_quantity(line: OrderLine, delta: int, *, user) -> OrderLine | None:
    line = OrderLine.objects.select_for_update().select_related("order").get(pk=line.pk)
    order = line.order
    _require_open(order)
    new_qty = line.quantity + delta
    if delta < 0 and order.total - line.unit_price * min(-delta, line.quantity) < order.paid:
        raise BusinessError(_("Part of this bill is already paid. Void the payment before removing items."))
    if new_qty <= 0:
        audit(user, "order.line_removed", f"#{order.number}: {line}", order)
        line.delete()
        return None
    line.quantity = new_qty
    line.save(update_fields=["quantity"])
    return line


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
) -> Payment:
    """Take a full or partial payment. The order closes when nothing is left to pay.

    For cash, `tendered` is what the customer handed over; the change is shown on the receipt.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require_open(order)
    if order.total <= 0:
        raise BusinessError(_("The order is empty."))
    remaining = order.remaining
    if amount is None:
        amount = remaining
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount <= 0:
        raise BusinessError(_("Enter an amount."))
    if amount > remaining:
        raise BusinessError(_("Only %(left)s is left to pay.") % {"left": f"{remaining:.2f}"})
    if tendered is not None:
        tendered = Decimal(tendered).quantize(Decimal("0.01"))
        if method != Payment.Method.CASH:
            tendered = None
        elif tendered < amount:
            raise BusinessError(_("The cash given is less than the amount."))
    payment = Payment.objects.create(
        order=order, amount=amount, method=method, reference=reference, tendered=tendered, created_by=user
    )
    audit(user, "order.payment", f"{order.outlet} #{order.number} {amount} ({method})", order)
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
    audit(user, "order.room_charge", f"{order.outlet} #{order.number} {remaining} → {reservation.room.number}", order)
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
    target.guests += order.guests
    target.note = " · ".join(n for n in (target.note, order.note) if n)[:255]
    target.save(update_fields=["guests", "note"])
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
    if order.lines.exists() and not user.is_manager:
        raise BusinessError(_("Only a manager can cancel an order that has items."))
    if order.payments.filter(voided=False).exists():
        raise BusinessError(_("This bill has payments. Void them first."))
    order.status = Order.Status.CANCELLED
    order.closed_at = timezone.now()
    order.closed_by = user
    order.save(update_fields=["status", "closed_at", "closed_by"])
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
    audit(user, "order.void", f"{order.outlet} #{order.number} {order.total} – {reason}", order)
    return order


def _close(order: Order, settlement: str, user) -> None:
    from apps.core.models import Sequence

    order.status = Order.Status.CLOSED
    order.settlement = settlement
    order.closed_at = timezone.now()
    order.closed_by = user
    order.receipt_number = Sequence.next("receipt", timezone.localdate().year)
    order.save(update_fields=["status", "settlement", "closed_at", "closed_by", "receipt_number"])
