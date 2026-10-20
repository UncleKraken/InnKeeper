"""
The morning breakfast list: the guests who slept here last night, how many, whether breakfast is in their
price, and who has eaten. Breakfast for guests whose booking doesn't include it goes on their bill.
"""

from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings, audit

from .models import BreakfastServed, Reservation


def guests_for(day: date) -> list[Reservation]:
    """Everyone who slept here the night before `day`: in house now, or left this morning."""
    stays = (
        Reservation.objects.filter(arrival__lt=day, departure__gte=day)
        .filter(Q(status=Reservation.Status.CHECKED_IN) | Q(status=Reservation.Status.CHECKED_OUT, departure=day))
        .select_related("guest", "room")
        .order_by("room__number")
    )
    served = {b.reservation_id: b for b in BreakfastServed.objects.filter(date=day)}
    out = []
    for r in stays:
        r.persons = r.adults + (r.children or 0)
        r.served = served.get(r.pk)
        out.append(r)
    return out


@transaction.atomic
def serve(reservation: Reservation, day: date, guests: int, user) -> BreakfastServed:
    """Mark a room's breakfast as served; charge it to the bill if it isn't included."""
    from apps.frontdesk import services as fd
    from apps.finance.models import Folio

    if guests < 1 or guests > 20:
        raise BusinessError(_("Enter how many had breakfast."))
    if BreakfastServed.objects.select_for_update().filter(reservation=reservation, date=day).exists():
        raise BusinessError(_("Breakfast for room %(n)s is already marked.") % {"n": reservation.room.number})
    hs = HotelSettings.load()
    charge = None
    if not reservation.breakfast_included:
        if hs.breakfast_price <= 0:
            raise BusinessError(_("Set the breakfast price in Settings → Breakfast first."))
        folio = Folio.objects.filter(reservation=reservation, status=Folio.Status.OPEN).first()
        if folio is None:
            raise BusinessError(_("The guest's bill is closed. Take the payment at the restaurant instead."))
        charge = fd.add_charge(
            folio, description=_("Breakfast"), quantity=guests, unit_price=hs.breakfast_price, user=user
        )
    b = BreakfastServed.objects.create(reservation=reservation, date=day, guests=guests, charge=charge, served_by=user)
    audit(user, "breakfast.served", f"{reservation.room.number} × {guests}{' (charged)' if charge else ''}", reservation)
    return b


@transaction.atomic
def undo(served: BreakfastServed, user) -> None:
    """A tap on the wrong room: remove the mark and void its charge."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.finance.models import Charge, Folio

    own_recent = served.served_by_id == user.pk and timezone.now() - served.created_at < timedelta(minutes=30)
    if not (user.is_manager or own_recent):
        raise BusinessError(_("Ask a manager to undo this."))
    if served.charge_id and not Folio.objects.filter(charges=served.charge_id, status=Folio.Status.OPEN).exists():
        raise BusinessError(_("The guest's bill is closed. Ask a manager to correct it."))
    if served.charge_id:
        Charge.objects.filter(pk=served.charge_id, voided=False).update(
            voided=True, void_reason=_("Breakfast marked by mistake"), voided_by=user, voided_at=timezone.now()
        )
    audit(user, "breakfast.undo", f"{served.reservation.room.number} {served.date}", served.reservation)
    served.delete()
