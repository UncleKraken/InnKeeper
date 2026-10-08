"""Online booking: availability, prices, creating bookings from the public page, and confirming them."""

import secrets
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core import email
from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings, audit

from . import services
from .models import Guest, Reservation, Room, RoomType
from .pricing import Quote, apply_quote, quote


@dataclass
class Offer:
    room_type: RoomType
    available: int
    quote: Quote

    @property
    def bookable(self) -> bool:
        return self.available > 0 and self.quote.meets_min_nights


def free_rooms(room_type: RoomType, arrival: date, departure: date):
    busy = Reservation.objects.filter(
        status__in=Reservation.ACTIVE_STATUSES, arrival__lt=departure, departure__gt=arrival
    ).values_list("room_id", flat=True)
    return (
        Room.objects.filter(room_type=room_type, is_active=True, out_of_order=False)
        .exclude(pk__in=busy)
        .order_by("floor", "number")
    )


def search(arrival: date, departure: date, adults: int, children: int) -> list[Offer]:
    types = RoomType.objects.filter(
        is_active=True, bookable_online=True, max_adults__gte=adults, max_children__gte=children
    ).order_by("sort_order", "base_rate", "name")
    offers = [Offer(rt, free_rooms(rt, arrival, departure).count(), quote(rt, arrival, departure)) for rt in types]
    return [o for o in offers if o.available > 0]


def check_dates(arrival: date, departure: date) -> str | None:
    """Reason the dates can't be booked online, or None."""
    hs = HotelSettings.load()
    today = timezone.localdate()
    if departure <= arrival:
        return _("Departure must be after arrival.")
    if (arrival - today).days < hs.booking_min_days_ahead:
        if hs.booking_min_days_ahead == 0:
            return _("Arrival can't be in the past.")
        return _("Bookings must be made at least %(n)s days ahead.") % {"n": hs.booking_min_days_ahead}
    if (arrival - today).days > hs.booking_max_days_ahead:
        return _("Bookings can be made up to %(n)s days ahead.") % {"n": hs.booking_max_days_ahead}
    if (departure - arrival).days > 60:
        return _("For stays longer than 60 nights, please contact us.")
    return None


def deposit_for(total: Decimal) -> Decimal:
    pct = HotelSettings.load().booking_deposit_percent
    return (total * pct / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP) if pct else Decimal("0.00")


def create_online_booking(
    room_type: RoomType,
    arrival: date,
    departure: date,
    adults: int,
    children: int,
    guest_data: dict,
    *,
    language: str,
    base_url: str = "",
) -> Reservation:
    hs = HotelSettings.load()
    if not hs.booking_open:
        raise BusinessError(_("Online booking is closed."))
    problem = check_dates(arrival, departure)
    if problem:
        raise BusinessError(problem)
    q = quote(room_type, arrival, departure)
    if not q.meets_min_nights:
        raise BusinessError(_("The minimum stay for these dates is %(n)s nights.") % {"n": q.min_nights})
    if adults > room_type.max_adults or children > room_type.max_children:
        raise BusinessError(_("Too many guests for this room."))

    guest = (
        Guest.objects.filter(
            Q(email__iexact=guest_data["email"]),
            first_name__iexact=guest_data["first_name"],
            last_name__iexact=guest_data["last_name"],
        ).first()
        if guest_data.get("email")
        else None
    )
    if guest is None:
        guest = Guest.objects.create(
            first_name=guest_data["first_name"],
            last_name=guest_data["last_name"],
            email=guest_data.get("email", ""),
            phone=guest_data.get("phone", ""),
            nationality=guest_data.get("nationality", ""),
        )
    else:
        changed = [f for f in ("phone", "nationality") if guest_data.get(f) and not getattr(guest, f)]
        for f in changed:
            setattr(guest, f, guest_data[f])
        if changed:
            guest.save(update_fields=changed)

    # Try each free room until one sticks (another booking may take a room at the same moment).
    for room in free_rooms(room_type, arrival, departure)[:10]:
        res = Reservation(
            guest=guest,
            room=room,
            arrival=arrival,
            departure=departure,
            adults=adults,
            children=children,
            source=Reservation.Source.WEBSITE,
            notes=guest_data.get("notes", ""),
            confirmed=not hs.booking_requires_confirmation,
            booking_token=secrets.token_urlsafe(16),
            guest_language=language,
        )
        apply_quote(res, q)
        res.deposit_due = deposit_for(q.total)
        try:
            services.save_reservation(res, None)
        except ValidationError:
            continue
        audit(None, "booking.online", f"{res.code} {guest} {room_type.code} {arrival}–{departure}", res)
        notify_new_booking(res, base_url)
        return res
    raise BusinessError(_("Sorry, this room type was just booked by someone else. Please choose another."))


# ---------- Confirming ----------


def confirm(reservation: Reservation, user, base_url: str = "") -> Reservation:
    if reservation.confirmed:
        return reservation
    if reservation.status != Reservation.Status.BOOKED:
        raise BusinessError(_("Only booked reservations can be confirmed."))
    reservation.confirmed = True
    reservation.save(update_fields=["confirmed"])
    audit(user, "booking.confirm", f"{reservation.code} {reservation.guest}", reservation)
    send_guest_email(reservation, "confirmed", base_url)
    return reservation


def decline(reservation: Reservation, user, reason: str = "", base_url: str = "") -> Reservation:
    services.cancel(reservation, user)
    reservation.refresh_from_db()
    if reason:
        reservation.notes = (reservation.notes + f"\n{_('Declined')}: {reason}").strip()
        reservation.save(update_fields=["notes"])
    send_guest_email(reservation, "declined", base_url, reason=reason)
    return reservation


# ---------- Emails ----------

SUBJECTS = {
    "received": gettext_lazy("We received your booking request %(code)s"),
    "confirmed": gettext_lazy("Your booking %(code)s is confirmed"),
    "declined": gettext_lazy("About your booking request %(code)s"),
}


def booking_url(reservation: Reservation, base_url: str = "") -> str:
    base = (HotelSettings.load().public_url or base_url).rstrip("/")
    return f"{base}{reverse('booking:status', args=[reservation.booking_token])}"


def send_guest_email(reservation: Reservation, kind: str, base_url: str = "", **extra) -> bool:
    if not reservation.guest.email:
        return False
    lang = reservation.guest_language or HotelSettings.load().default_language
    from django.utils import translation

    with translation.override(lang):
        subject = str(SUBJECTS[kind]) % {"code": reservation.code}
    return email.send(
        reservation.guest.email,
        subject,
        "booking/email_guest.html",
        {"r": reservation, "kind": kind, "url": booking_url(reservation, base_url), **extra},
        language=lang,
    )


def notify_new_booking(reservation: Reservation, base_url: str = "") -> None:
    hs = HotelSettings.load()
    send_guest_email(reservation, "confirmed" if reservation.confirmed else "received", base_url)
    if hs.notify_email:
        email.send(
            hs.notify_email,
            f"{_('New online booking')} {reservation.code} – {reservation.guest} ({reservation.arrival:%d.%m}–{reservation.departure:%d.%m})",
            "booking/email_staff.html",
            {
                "r": reservation,
                "url": (hs.public_url or base_url).rstrip("/") + reverse("frontdesk:reservation_detail", args=[reservation.pk]),
            },
            reply_to=[reservation.guest.email] if reservation.guest.email else None,
        )
