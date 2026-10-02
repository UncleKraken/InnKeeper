"""Outlet (restaurant, bar, spa…) business rules."""

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
    _require_open(line.order)
    new_qty = line.quantity + delta
    if new_qty <= 0:
        audit(user, "order.line_removed", f"#{line.order.number}: {line}", line.order)
        line.delete()
        return None
    line.quantity = new_qty
    line.save(update_fields=["quantity"])
    return line


@transaction.atomic
def pay_order(order: Order, *, method: str, user, reference: str = "") -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require_open(order)
    total = order.total
    if total <= 0:
        raise BusinessError(_("The order is empty."))
    Charge.objects.create(
        order=order,
        outlet=order.outlet,
        kind=Charge.Kind.OUTLET,
        description=f"{order.outlet} – {order.display_name}",
        quantity=1,
        unit_price=total,
        created_by=user,
    )
    Payment.objects.create(order=order, amount=total, method=method, reference=reference, created_by=user)
    _close(order, Order.Settlement.PAID, user)
    audit(user, "order.paid", f"{order.outlet} #{order.number} {total} ({method})", order)
    return order


@transaction.atomic
def charge_to_room(order: Order, reservation: Reservation, *, user) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require_open(order)
    total = order.total
    if total <= 0:
        raise BusinessError(_("The order is empty."))
    if reservation.status != Reservation.Status.CHECKED_IN:
        raise BusinessError(_("Only in-house guests can charge to their room."))
    folio, _created = Folio.objects.select_for_update().get_or_create(reservation=reservation)
    if folio.status != Folio.Status.OPEN:
        raise BusinessError(_("This guest's bill is closed."))
    Charge.objects.create(
        folio=folio,
        order=order,
        outlet=order.outlet,
        kind=Charge.Kind.OUTLET,
        description=f"{order.outlet} – #{order.number}",
        quantity=1,
        unit_price=total,
        created_by=user,
    )
    _close(order, Order.Settlement.ROOM, user)
    audit(user, "order.room_charge", f"{order.outlet} #{order.number} {total} → {reservation.room.number}", order)
    return order


@transaction.atomic
def cancel_order(order: Order, *, user) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require_open(order)
    if order.lines.exists() and not user.is_manager:
        raise BusinessError(_("Only a manager can cancel an order that has items."))
    order.status = Order.Status.CANCELLED
    order.closed_at = timezone.now()
    order.closed_by = user
    order.save(update_fields=["status", "closed_at", "closed_by"])
    audit(user, "order.cancel", f"{order.outlet} #{order.number} {order.total}", order)
    return order


def _close(order: Order, settlement: str, user) -> None:
    order.status = Order.Status.CLOSED
    order.settlement = settlement
    order.closed_at = timezone.now()
    order.closed_by = user
    order.save(update_fields=["status", "settlement", "closed_at", "closed_by"])
