from datetime import date

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings

from . import breakfast
from .models import BreakfastServed, Reservation


def _day(request) -> date:
    try:
        return date.fromisoformat(request.GET.get("date") or request.POST.get("date") or "")
    except ValueError:
        return timezone.localdate()


@module_required("frontdesk", "outlets")
def breakfast_list(request):
    if not HotelSettings.load().breakfast_on:
        raise Http404
    day = _day(request)
    rows = breakfast.guests_for(day)
    return render(
        request,
        "frontdesk/breakfast.html",
        {
            "day": day,
            "rows": rows,
            "prev": day.fromordinal(day.toordinal() - 1),
            "next": day.fromordinal(day.toordinal() + 1),
            "expected": sum(r.persons for r in rows),
            "included": sum(r.persons for r in rows if r.breakfast_included),
            "served": sum(r.served.guests for r in rows if r.served),
            "rooms_served": sum(1 for r in rows if r.served),
        },
    )


@require_POST
@module_required("frontdesk", "outlets")
def breakfast_serve(request, pk):
    res = get_object_or_404(Reservation.objects.select_related("room"), pk=pk)
    day = _day(request)
    back = f"{reverse('frontdesk:breakfast')}?date={day.isoformat()}"
    if request.POST.get("undo"):
        served = get_object_or_404(BreakfastServed, reservation=res, date=day)
        try:
            breakfast.undo(served, request.user)
        except BusinessError as e:
            messages.error(request, str(e))
        return redirect(back)
    try:
        guests = int(request.POST.get("guests") or 0)
        b = breakfast.serve(res, day, guests, request.user)
        if b.charge_id:
            messages.success(request, _("Room %(n)s: %(g)s breakfast(s) added to the bill.") % {"n": res.room.number, "g": guests})
    except (ValueError, BusinessError) as e:
        messages.error(request, str(e) if isinstance(e, BusinessError) else _("Enter how many had breakfast."))
    return redirect(back)
