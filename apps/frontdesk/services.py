"""Front-desk business rules. Views call these; they never change stays directly."""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import BusinessError
from apps.core.models import audit
from apps.finance.models import Charge, Folio, Payment

from .models import Reservation, Room


def _lock_room(room_id: int) -> Room:
    # Serialises bookings for the same room so two receptionists can't double-book it.
    return Room.objects.select_for_update().get(pk=room_id)


@transaction.atomic
def save_reservation(reservation: Reservation, user) -> Reservation:
    """Create or update a reservation after validating dates, capacity and availability."""
    _lock_room(reservation.room_id)
    is_new = reservation.pk is None
    if not is_new and reservation.status not in Reservation.ACTIVE_STATUSES:
        raise BusinessError(_("Closed or cancelled reservations cannot be changed."))
    reservation.full_clean()
    if is_new:
        reservation.created_by = user
    reservation.save()
    Folio.objects.get_or_create(reservation=reservation)
    audit(
        user,
        "reservation.create" if is_new else "reservation.update",
        f"{reservation.code} {reservation.guest}",
        reservation,
    )
    return reservation


@transaction.atomic
def check_in(reservation: Reservation, user) -> Reservation:
    reservation = Reservation.objects.select_for_update().select_related("room", "guest").get(pk=reservation.pk)
    if reservation.status != Reservation.Status.BOOKED:
        raise BusinessError(_("Only booked reservations can be checked in."))
    today = timezone.localdate()
    if reservation.arrival > today:
        raise BusinessError(
            _("This reservation arrives on %(d)s. Change the arrival date to check in early.")
            % {"d": reservation.arrival.strftime("%d.%m.%Y")}
        )
    if reservation.departure <= today:
        raise BusinessError(_("The departure date has already passed. Update the dates first."))
    room = _lock_room(reservation.room_id)
    if room.out_of_order:
        raise BusinessError(_("Room %(n)s is out of order.") % {"n": room.number})
    occupant = room.reservations.filter(status=Reservation.Status.CHECKED_IN).exclude(pk=reservation.pk).first()
    if occupant:
        raise BusinessError(_("Room %(n)s is still occupied by %(g)s.") % {"n": room.number, "g": occupant.guest})
    reservation.status = Reservation.Status.CHECKED_IN
    reservation.checked_in_at = timezone.now()
    reservation.save(update_fields=["status", "checked_in_at"])
    Folio.objects.get_or_create(reservation=reservation)
    audit(user, "reservation.check_in", f"{reservation.code} {reservation.guest} → {room.number}", reservation)
    return reservation


@transaction.atomic
def post_accommodation(
    reservation: Reservation, user, on_date: date | None = None, *, night_audit: bool = False
) -> Charge | None:
    """Post any room nights not yet charged, up to `on_date`. Safe to call repeatedly.

    At check-out at least one night is always charged. The nightly audit only
    charges nights that have fully passed, dated to the night itself.
    """
    folio, _created = Folio.objects.select_for_update().get_or_create(reservation=reservation)
    on_date = on_date or timezone.localdate()
    if night_audit:
        nights_due = min((on_date - reservation.arrival).days, reservation.nights)
    else:
        nights_due = reservation.nights_to_charge(on_date)
    posted = folio.accommodation_nights_posted()
    if nights_due <= posted:
        return None
    # One charge per run of nights with the same price (seasons can change the price mid-stay).
    first = None
    start = posted
    while start < nights_due:
        price = reservation.rate_for_night(start)
        end = start + 1
        while end < nights_due and reservation.rate_for_night(end) == price:
            end += 1
        charge = Charge.objects.create(
            folio=folio,
            kind=Charge.Kind.ACCOMMODATION,
            description=_("Accommodation – room %(room)s") % {"room": reservation.room.number},
            quantity=end - start,
            unit_price=price,
            business_date=on_date - timedelta(days=1) if night_audit else on_date,
            created_by=user,
        )
        audit(user, "folio.accommodation", f"{folio.number}: {end - start} × {price}", folio)
        first = first or charge
        start = end
    return first


def night_audit(on_date: date | None = None) -> int:
    """Post last night's room charge for every in-house guest. Run once a day (see README)."""
    posted = 0
    for res in Reservation.objects.filter(status=Reservation.Status.CHECKED_IN).select_related("room"):
        if post_accommodation(res, None, on_date, night_audit=True):
            posted += 1
    return posted


def check_out(reservation: Reservation, user, *, allow_balance: bool = False) -> Reservation:
    """Post room charges, require a settled bill, release the room to housekeeping."""
    if reservation.status != Reservation.Status.CHECKED_IN:
        raise BusinessError(_("Only guests who are in house can be checked out."))
    post_accommodation(reservation, user)

    with transaction.atomic():
        reservation = Reservation.objects.select_for_update().select_related("room", "guest").get(pk=reservation.pk)
        folio = Folio.objects.select_for_update().get(reservation=reservation)
        balance = folio.balance
        if balance > 0 and not allow_balance:
            raise BusinessError(
                _("The guest still owes %(amount)s. Take payment before checking out.") % {"amount": f"{balance:.2f}"}
            )

        today = timezone.localdate()
        reservation.status = Reservation.Status.CHECKED_OUT
        reservation.checked_out_at = timezone.now()
        if reservation.departure != today and today > reservation.arrival:
            reservation.departure = today
        reservation.save(update_fields=["status", "checked_out_at", "departure"])

        if balance <= 0:
            _close_folio(folio)

        from apps.housekeeping.services import room_vacated

        room_vacated(reservation.room, user)
        audit(
            user,
            "reservation.check_out",
            f"{reservation.code} {reservation.guest} balance {balance:.2f}",
            reservation,
        )
    return reservation


@transaction.atomic
def cancel(reservation: Reservation, user, *, no_show: bool = False) -> Reservation:
    reservation = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if reservation.status != Reservation.Status.BOOKED:
        raise BusinessError(_("Only booked reservations can be cancelled."))
    reservation.status = Reservation.Status.NO_SHOW if no_show else Reservation.Status.CANCELLED
    reservation.cancelled_at = timezone.now()
    reservation.save(update_fields=["status", "cancelled_at"])
    audit(
        user,
        "reservation.no_show" if no_show else "reservation.cancel",
        f"{reservation.code} {reservation.guest}",
        reservation,
    )
    return reservation


def _close_folio(folio: Folio) -> None:
    """Close a settled bill and give it the next invoice number."""
    from apps.core.models import Sequence

    folio.status = Folio.Status.CLOSED
    folio.closed_at = timezone.now()
    if not folio.invoice_number:
        folio.invoice_number = Sequence.next("invoice", timezone.localdate().year)
    folio.save(update_fields=["status", "closed_at", "invoice_number"])
    from apps.fiscal import services as fiscal

    transaction.on_commit(lambda: fiscal.safely(fiscal.fiscalize_folio, folio, None))


def _require_open(folio: Folio) -> None:
    if folio.status != Folio.Status.OPEN:
        raise BusinessError(_("This bill is closed."))


@transaction.atomic
def add_charge(
    folio: Folio, *, description: str, quantity: int, unit_price: Decimal, user, outlet=None, order=None
) -> Charge:
    folio = Folio.objects.select_for_update().get(pk=folio.pk)
    _require_open(folio)
    if quantity < 1 or unit_price < 0:
        raise BusinessError(_("Quantity must be at least 1 and the price cannot be negative."))
    charge = Charge.objects.create(
        folio=folio,
        kind=Charge.Kind.OUTLET if outlet else Charge.Kind.EXTRA,
        outlet=outlet,
        order=order,
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        created_by=user,
    )
    audit(user, "folio.charge", f"{folio.number}: {description} {charge.amount}", folio)
    return charge


@transaction.atomic
def add_payment(folio: Folio, *, amount: Decimal, method: str, reference: str = "", user) -> Payment:
    folio = Folio.objects.select_for_update().get(pk=folio.pk)
    _require_open(folio)
    if amount == 0:
        raise BusinessError(_("Enter an amount."))
    payment = Payment.objects.create(folio=folio, amount=amount, method=method, reference=reference, created_by=user)
    audit(user, "folio.payment", f"{folio.number}: {payment.get_method_display()} {amount}", folio)
    if folio.balance == 0 and folio.reservation.status in (
        Reservation.Status.CHECKED_OUT,
        Reservation.Status.CANCELLED,
    ):
        _close_folio(folio)
    return payment


@transaction.atomic
def void_entry(entry, *, reason: str, user):
    """Void a charge or payment. Managers only; a reason is required."""
    if not user.is_manager:
        raise BusinessError(_("Only a manager can void entries."))
    if not reason.strip():
        raise BusinessError(_("Give a reason for the void."))
    entry = type(entry).objects.select_for_update().get(pk=entry.pk)
    if entry.voided:
        raise BusinessError(_("Already voided."))
    if entry.folio_id:
        _require_open(entry.folio)
    entry.voided = True
    entry.void_reason = reason.strip()[:255]
    entry.voided_by = user
    entry.voided_at = timezone.now()
    entry.save(update_fields=["voided", "void_reason", "voided_by", "voided_at"])
    audit(user, f"{entry._meta.model_name}.void", f"{entry} – {reason}", entry)
    return entry


@transaction.atomic
def move_room(reservation: Reservation, new_room: Room, user, *, use_new_rate: bool = False) -> Reservation:
    """Move a booked or in-house guest to another room, checking it is free for the stay."""
    reservation = Reservation.objects.select_for_update().select_related("room").get(pk=reservation.pk)
    if reservation.status not in Reservation.ACTIVE_STATUSES:
        raise BusinessError(_("Closed or cancelled reservations cannot be changed."))
    if new_room.pk == reservation.room_id:
        return reservation
    _lock_room(new_room.pk)
    if new_room.out_of_order:
        raise BusinessError(_("Room %(n)s is out of order.") % {"n": new_room.number})
    old_room = reservation.room
    reservation.room = new_room
    if reservation.status == Reservation.Status.CHECKED_IN:
        # From today on; past nights stay as they were.
        occupant = new_room.reservations.filter(status=Reservation.Status.CHECKED_IN).exclude(pk=reservation.pk).first()
        if occupant:
            raise BusinessError(
                _("Room %(n)s is still occupied by %(g)s.") % {"n": new_room.number, "g": occupant.guest}
            )
    if use_new_rate:
        reservation.rate = new_room.room_type.base_rate
    reservation.full_clean()
    reservation.save(update_fields=["room", "rate"])
    if reservation.status == Reservation.Status.CHECKED_IN:
        from apps.housekeeping.services import room_vacated

        room_vacated(old_room, user)
    audit(user, "reservation.move_room", f"{reservation.code}: {old_room.number} → {new_room.number}", reservation)
    return reservation
