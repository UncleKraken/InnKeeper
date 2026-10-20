"""
Minibar check: while cleaning, the housekeeper counts what was taken and it goes straight on the guest's
bill, through a minibar bill (so stock and reports are right).
"""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.accounts.permissions import module_required
from apps.core.exceptions import BusinessError
from apps.frontdesk.models import Reservation, Room
from apps.outlets import services as pos
from apps.outlets.models import Item, Outlet


def minibar_outlet():
    return Outlet.objects.filter(kind=Outlet.Kind.MINIBAR, is_active=True).order_by("sort_order", "pk").first()


@transaction.atomic
def charge(room: Room, quantities: dict[int, int], user):
    """Put what was taken from the minibar on the bill of the guest in the room."""
    outlet = minibar_outlet()
    if outlet is None:
        raise BusinessError(_("There is no minibar yet. Add an outlet of the type Minibar with its items."))
    res = Reservation.objects.filter(room=room, status=Reservation.Status.CHECKED_IN).first()
    if res is None:
        raise BusinessError(_("Nobody is staying in room %(n)s, so there is no bill to charge.") % {"n": room.number})
    taken = {pk: q for pk, q in quantities.items() if q > 0}
    if not taken:
        raise BusinessError(_("Nothing was taken."))
    items = {i.pk: i for i in Item.objects.filter(pk__in=taken, category__outlet=outlet)}
    if len(items) != len(taken):
        raise BusinessError(_("Something on the minibar list changed. Open the page again."))
    order = pos.open_order(outlet, user=user, label=_("Room %(n)s") % {"n": room.number})
    for pk, q in taken.items():
        pos.add_item(order, items[pk], user=user, quantity=min(q, 50))
    pos.charge_to_room(order, res, user=user)
    order.refresh_from_db()
    return order, res


@module_required("housekeeping")
def minibar(request, pk):
    room = get_object_or_404(Room, pk=pk)
    outlet = minibar_outlet()
    items = list(Item.objects.filter(category__outlet=outlet, is_active=True).select_related("category")) if outlet else []
    guest = Reservation.objects.filter(room=room, status=Reservation.Status.CHECKED_IN).select_related("guest").first()
    if request.method == "POST":
        quantities = {}
        for i in items:
            try:
                quantities[i.pk] = max(0, int(request.POST.get(f"q{i.pk}") or 0))
            except ValueError:
                quantities[i.pk] = 0
        try:
            order, res = charge(room, quantities, request.user)
            messages.success(request, _("Room %(n)s: %(total)s added to %(guest)s's bill.") % {"n": room.number, "total": f"{order.total:.2f}", "guest": res.guest})
            return redirect("housekeeping:board")
        except BusinessError as e:
            messages.error(request, str(e))
    return render(request, "housekeeping/minibar.html", {"room": room, "outlet": outlet, "items": items, "guest": guest})
