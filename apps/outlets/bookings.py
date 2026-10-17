"""Table bookings: the rules. Views are in booking_views.py."""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import BusinessError
from apps.core.models import audit

from .models import Order, OrderLine, TableBooking

ACTIVE = (TableBooking.Status.BOOKED, TableBooking.Status.SEATED)


@transaction.atomic
def save_booking(booking: TableBooking, user) -> TableBooking:
    if booking.table_id and booking.table.outlet_id != booking.outlet_id:
        raise BusinessError(_("That table belongs to another outlet."))
    booking.full_clean(exclude=["created_by"])
    if booking.table_id and booking.status in ACTIVE:
        clash = _clash(booking)
        if clash:
            raise BusinessError(
                _("Table %(table)s is already booked for %(name)s at %(time)s.")
                % {"table": booking.table.name, "name": clash.name, "time": f"{clash.time:%H:%M}"}
            )
    is_new = booking.pk is None
    if is_new:
        booking.created_by = user
    booking.save()
    audit(user, "booking.create" if is_new else "booking.update", str(booking), booking)
    return booking


def _clash(booking: TableBooking) -> TableBooking | None:
    """Another booking on the same table whose time overlaps (it may start the evening before)."""
    candidates = TableBooking.objects.filter(
        table_id=booking.table_id,
        status__in=ACTIVE,
        date__range=(booking.date - timedelta(days=1), booking.date + timedelta(days=1)),
    ).exclude(pk=booking.pk)
    for other in candidates:
        if other.starts_at < booking.ends_at and booking.starts_at < other.ends_at:
            return other
    return None


@transaction.atomic
def seat(booking: TableBooking, user, table=None) -> Order:
    """The guests arrived: open their order on the table (with their name and party size)."""
    from . import services

    booking = TableBooking.objects.select_for_update().get(pk=booking.pk)
    if booking.status != TableBooking.Status.BOOKED:
        raise BusinessError(_("This booking is not waiting any more."))
    table = table or booking.table
    if table is None:
        raise BusinessError(_("Choose a table first."))
    if table.open_order():
        raise BusinessError(_("Table %(table)s still has an open bill.") % {"table": table.name})
    booking.table = table
    order = services.open_order(booking.outlet, user=user, table=table, guests=booking.party_size, label=booking.name)
    if booking.note:
        order.note = booking.note[:255]
        order.save(update_fields=["note"])
    booking.order = order
    booking.status = TableBooking.Status.SEATED
    booking.save(update_fields=["table", "order", "status"])
    audit(user, "booking.seat", str(booking), booking)
    return order


def set_status(booking: TableBooking, status: str, user) -> TableBooking:
    if booking.status != TableBooking.Status.BOOKED:
        raise BusinessError(_("This booking is not waiting any more."))
    booking.status = status
    booking.save(update_fields=["status"])
    audit(user, f"booking.{status}", str(booking), booking)
    return booking


def upcoming_by_table(outlet, now=None, hours: int = 3) -> dict[int, TableBooking]:
    """Bookings to show on the floor plan: starting within the next few hours (or late by up to 30 min)."""
    now = now or timezone.now()
    local = timezone.localtime(now)
    out: dict[int, TableBooking] = {}
    qs = TableBooking.objects.filter(
        outlet=outlet,
        status=TableBooking.Status.BOOKED,
        table__isnull=False,
        date__range=(local.date() - timedelta(days=1), local.date() + timedelta(days=1)),
    ).order_by("date", "time")
    for b in qs:
        if now - timedelta(minutes=30) <= b.starts_at <= now + timedelta(hours=hours):
            out.setdefault(b.table_id, b)
    return out


# ---------- Minimum spend ----------


def minimum_spend_left(order: Order) -> Decimal:
    booking = getattr(order, "booking", None)
    if not booking or not booking.minimum_spend:
        return Decimal("0")
    return max(booking.minimum_spend - order.subtotal, Decimal("0"))


@transaction.atomic
def top_up_minimum_spend(order: Order, user) -> OrderLine:
    """Add the difference to the minimum spend as a line on the bill."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != Order.Status.OPEN:
        raise BusinessError(_("This bill is already closed."))
    left = minimum_spend_left(order)
    if left <= 0:
        raise BusinessError(_("The minimum spend is already reached."))
    line = OrderLine.objects.create(
        order=order,
        item=None,
        name=str(_("Minimum spend – difference")),
        unit_price=left,
        quantity=1,
        status=OrderLine.Status.DIRECT,
        added_by=user,
    )
    audit(user, "booking.minimum_spend", f"#{order.number} +{left}", order)
    return line
