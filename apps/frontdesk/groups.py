"""Group bookings: several rooms booked together, optionally paid on one bill."""

from datetime import date, timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Min, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.permissions import module_required
from apps.core.exceptions import BusinessError
from apps.core.forms import DateInput, StyledFormMixin
from apps.core.models import audit
from apps.finance.models import Folio

from . import services
from .booking import free_rooms
from .models import Group, Guest, Reservation, Room, RoomType
from .pricing import apply_quote, quote

# ---------- Rules ----------


@transaction.atomic
def create_group(
    *,
    name: str,
    contact: Guest,
    rooms: list[Room],
    arrival: date,
    departure: date,
    adults: int,
    user,
    rate: Decimal | None = None,
    one_bill: bool = True,
    company: str = "",
    notes: str = "",
    source: str = Reservation.Source.PHONE,
) -> Group:
    if not rooms:
        raise BusinessError(_("Choose at least one room."))
    group = Group.objects.create(
        name=name, contact=contact, company=company, one_bill=one_bill, notes=notes, created_by=user
    )
    for room in sorted(rooms, key=lambda r: (r.floor, r.number)):
        res = Reservation(
            guest=contact,
            room=room,
            arrival=arrival,
            departure=departure,
            adults=min(adults, room.room_type.max_adults),
            source=source,
            group=group,
            notes=notes,
        )
        if rate is None:
            apply_quote(res, quote(room.room_type, arrival, departure))
        else:
            res.rate = rate
        try:
            services.save_reservation(res, user)
        except ValidationError as e:
            msgs = " ".join(m for v in e.message_dict.values() for m in v)
            raise BusinessError(msgs)
        if group.master_id is None:
            group.master = res
    group.save(update_fields=["master"])
    audit(user, "group.create", f"{group.code} {group} ({len(rooms)} rooms)", group)
    return group


@transaction.atomic
def move_to_master(reservation: Reservation, user) -> int:
    """Move a room's charges and payments to the group's main bill. Returns how many entries moved."""
    group = reservation.group
    if not group or not group.one_bill or not group.master_id or group.master_id == reservation.pk:
        return 0
    master_folio = Folio.objects.select_for_update().get(reservation_id=group.master_id)
    folio = Folio.objects.select_for_update().get(reservation=reservation)
    if master_folio.status != Folio.Status.OPEN or folio.status != Folio.Status.OPEN:
        return 0
    moved = folio.charges.filter(voided=False).update(folio=master_folio)
    moved += folio.payments.filter(voided=False).update(folio=master_folio)
    if moved:
        audit(user, "group.move_bill", f"{reservation.code} → {group.master.code}: {moved} entries", reservation)
    return moved


def group_check_out(reservation: Reservation, user, *, allow_balance: bool = False) -> Reservation:
    """Check-out for a group room. On a shared bill, other rooms' charges go to the main room's bill."""
    reservation = Reservation.objects.select_related("group").get(pk=reservation.pk)
    group = reservation.group
    shared = bool(
        group
        and group.one_bill
        and group.master_id
        and Folio.objects.filter(reservation_id=group.master_id, status=Folio.Status.OPEN).exists()
    )
    if shared and group.master_id != reservation.pk:
        # Post the nights on this room's bill, then hand everything over to the main room.
        reservation = services.check_out(reservation, user, allow_balance=True)
        if move_to_master(reservation, user):
            Folio.objects.filter(reservation=reservation, status=Folio.Status.OPEN).update(
                status=Folio.Status.CLOSED, closed_at=timezone.now()
            )
        return reservation
    if shared:
        for other in group.reservations.filter(status__in=Reservation.ACTIVE_STATUSES).exclude(pk=reservation.pk):
            move_to_master(other, user)
    return services.check_out(reservation, user, allow_balance=allow_balance)


# ---------- Views ----------


class GroupForm(StyledFormMixin, forms.Form):
    name = forms.CharField(label=gettext_lazy("Group name"), max_length=120)
    contact_first = forms.CharField(label=gettext_lazy("Contact first name"), max_length=80)
    contact_last = forms.CharField(label=gettext_lazy("Contact last name"), max_length=80)
    contact_phone = forms.CharField(label=gettext_lazy("Phone"), max_length=40, required=False)
    contact_email = forms.EmailField(label=gettext_lazy("Email"), required=False)
    company = forms.CharField(label=gettext_lazy("Company / agency"), max_length=120, required=False)
    arrival = forms.DateField(label=gettext_lazy("Arrival"), widget=DateInput)
    departure = forms.DateField(label=gettext_lazy("Departure"), widget=DateInput)
    adults = forms.IntegerField(label=gettext_lazy("Adults per room"), min_value=1, max_value=8, initial=2)
    rate = forms.DecimalField(
        label=gettext_lazy("Group rate per night"),
        required=False,
        min_value=0,
        decimal_places=2,
        help_text=gettext_lazy("Leave empty to use the price list."),
    )
    source = forms.ChoiceField(label=gettext_lazy("Source"), choices=Reservation.Source.choices, initial="phone")
    one_bill = forms.BooleanField(
        label=gettext_lazy("One bill for the whole group"),
        required=False,
        initial=True,
        help_text=gettext_lazy("The first room pays for everyone: other rooms' charges move to its bill at check-out."),
    )
    notes = forms.CharField(label=gettext_lazy("Notes"), required=False, widget=forms.Textarea)

    def clean(self):
        cleaned = super().clean()
        a, d = cleaned.get("arrival"), cleaned.get("departure")
        if a and d and d <= a:
            self.add_error("departure", _("Departure must be after arrival."))
        return cleaned


@module_required("frontdesk")
def group_list(request):
    today = timezone.localdate()
    show = request.GET.get("show", "current")
    qs = Group.objects.select_related("contact").annotate(
        rooms=Count("reservations", filter=~Q(reservations__status=Reservation.Status.CANCELLED)),
        first_arrival=Min("reservations__arrival"),
    )
    if show == "current":
        qs = qs.filter(reservations__departure__gte=today).distinct()
    return render(request, "frontdesk/groups.html", {"groups": qs.order_by("first_arrival")[:200], "show": show})


@module_required("frontdesk")
def group_create(request):
    today = timezone.localdate()
    data = request.POST if request.method == "POST" else None
    form = GroupForm(
        data, initial={"arrival": today, "departure": today + timedelta(days=2), "adults": 2, "one_bill": True}
    )
    arrival = departure = None
    if form.is_bound and form.is_valid():
        arrival, departure = form.cleaned_data["arrival"], form.cleaned_data["departure"]
    chosen = set(request.POST.getlist("rooms"))
    if request.method == "POST" and request.POST.get("action") == "save" and form.is_valid():
        d = form.cleaned_data
        rooms = list(Room.objects.filter(pk__in=chosen, is_active=True).select_related("room_type"))
        try:
            with transaction.atomic():
                contact = Guest.objects.create(
                    first_name=d["contact_first"],
                    last_name=d["contact_last"],
                    phone=d["contact_phone"],
                    email=d["contact_email"],
                    company=d["company"],
                )
                group = create_group(
                    name=d["name"],
                    contact=contact,
                    rooms=rooms,
                    arrival=d["arrival"],
                    departure=d["departure"],
                    adults=d["adults"],
                    rate=d["rate"],
                    one_bill=d["one_bill"],
                    company=d["company"],
                    notes=d["notes"],
                    source=d["source"],
                    user=request.user,
                )
        except BusinessError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, _("Group booked: %(n)s rooms.") % {"n": len(rooms)})
            return redirect("frontdesk:group_detail", pk=group.pk)
    available = []
    if arrival and departure:
        for rt in RoomType.objects.filter(is_active=True).order_by("sort_order", "base_rate"):
            rooms = list(free_rooms(rt, arrival, departure).select_related("room_type"))
            if rooms:
                q = quote(rt, arrival, departure)
                available.append({"type": rt, "rooms": rooms, "average": q.average, "total": q.total})
    return render(
        request,
        "frontdesk/group_form.html",
        {"form": form, "available": available, "chosen": chosen, "searched": bool(arrival)},
    )


@module_required("frontdesk")
def group_detail(request, pk):
    group = get_object_or_404(Group.objects.select_related("contact", "master__room"), pk=pk)
    members = list(
        group.reservations.select_related("guest", "room__room_type", "folio").order_by("room__floor", "room__number")
    )
    today = timezone.localdate()
    active = [r for r in members if r.status != Reservation.Status.CANCELLED]
    return render(
        request,
        "frontdesk/group_detail.html",
        {
            "group": group,
            "members": members,
            "total": sum((r.estimated_total for r in active), Decimal("0")),
            "balance": sum((r.folio.balance for r in active if hasattr(r, "folio")), Decimal("0")),
            "can_check_in": [r for r in members if r.status == Reservation.Status.BOOKED and r.arrival <= today],
            "in_house": [r for r in members if r.status == Reservation.Status.CHECKED_IN],
            "booked": [r for r in members if r.status == Reservation.Status.BOOKED],
        },
    )


@module_required("frontdesk")
def group_action(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method != "POST":
        return redirect("frontdesk:group_detail", pk=pk)
    action = request.POST.get("action")
    done, problems = 0, []
    members = group.reservations.select_related("room", "guest").order_by("room__number")
    if action == "check_in":
        for r in members.filter(status=Reservation.Status.BOOKED, arrival__lte=timezone.localdate()):
            try:
                services.check_in(r, request.user)
                done += 1
            except BusinessError as e:
                problems.append(f"{r.room.number}: {e}")
        messages.success(request, _("%(n)s room(s) checked in.") % {"n": done})
    elif action == "check_out":
        # Everyone else first, the main room (which pays) last.
        rooms = sorted(members.filter(status=Reservation.Status.CHECKED_IN), key=lambda r: r.pk == group.master_id)
        for r in rooms:
            try:
                group_check_out(r, request.user)
                done += 1
            except BusinessError as e:
                problems.append(f"{r.room.number}: {e}")
        messages.success(request, _("%(n)s room(s) checked out.") % {"n": done})
    elif action == "cancel":
        for r in members.filter(status=Reservation.Status.BOOKED):
            services.cancel(r, request.user)
            done += 1
        audit(request.user, "group.cancel", f"{group.code} {group}", group)
        messages.success(request, _("%(n)s room(s) cancelled.") % {"n": done})
    elif action == "master":
        res = get_object_or_404(Reservation, pk=request.POST.get("reservation"), group=group)
        group.master = res
        group.save(update_fields=["master"])
        messages.success(request, _("Room %(room)s now pays for the group.") % {"room": res.room.number})
    elif action == "one_bill":
        group.one_bill = request.POST.get("value") == "1"
        group.save(update_fields=["one_bill"])
    elif action == "move_bills":
        for r in members.filter(status__in=Reservation.ACTIVE_STATUSES).exclude(pk=group.master_id):
            done += move_to_master(r, request.user)
        messages.success(request, _("%(n)s bill entries moved to the main room.") % {"n": done})
    for p in problems:
        messages.error(request, p)
    return redirect("frontdesk:group_detail", pk=pk)
