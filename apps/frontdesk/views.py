from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.crud import CrudCreateView, CrudListView, CrudUpdateView
from apps.core.exceptions import BusinessError
from apps.finance.models import Charge, Folio, Payment

from . import services
from .forms import (
    ChargeForm,
    GuestForm,
    PaymentForm,
    ReservationForm,
    RoomForm,
    RoomTypeForm,
    VoidForm,
)
from .models import Guest, Reservation, Room, RoomType


def _parse_date(value, default: date) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def _business_error(request, exc: Exception) -> None:
    if isinstance(exc, ValidationError):
        for msgs in exc.message_dict.values() if hasattr(exc, "message_dict") else [exc.messages]:
            for m in msgs:
                messages.error(request, m)
    else:
        messages.error(request, str(exc))


# ---------- Room rack ----------


@module_required("frontdesk")
def rack(request):
    today = timezone.localdate()
    days = min(max(int(request.GET.get("days", 14) or 14), 7), 31)
    start = _parse_date(request.GET.get("start"), today - timedelta(days=1))
    end = start + timedelta(days=days)
    dates = [start + timedelta(days=i) for i in range(days)]

    rooms = list(Room.objects.filter(is_active=True).select_related("room_type"))
    stays = (
        Reservation.objects.filter(
            room__in=rooms,
            arrival__lt=end,
            departure__gt=start,
            status__in=[Reservation.Status.BOOKED, Reservation.Status.CHECKED_IN, Reservation.Status.CHECKED_OUT],
        )
        .select_related("guest")
        .order_by("arrival")
    )
    by_room: dict[int, list[Reservation]] = {}
    for r in stays:
        by_room.setdefault(r.room_id, []).append(r)

    rows = []
    for room in rooms:
        cells, i = [], 0
        room_stays = by_room.get(room.pk, [])
        while i < days:
            d = dates[i]
            stay = next((r for r in room_stays if r.arrival <= d < r.departure), None)
            if stay:
                span_end = min(stay.departure, end)
                span = (span_end - d).days
                cells.append({"kind": "stay", "span": span, "res": stay})
                i += span
            else:
                cells.append({"kind": "free", "date": d, "today": d == today, "blocked": room.out_of_order})
                i += 1
        rows.append({"room": room, "cells": cells})

    return render(
        request,
        "frontdesk/rack.html",
        {
            "rows": rows,
            "dates": dates,
            "today": today,
            "start": start,
            "days": days,
            "prev": start - timedelta(days=7),
            "next": start + timedelta(days=7),
        },
    )


# ---------- Reservations ----------

LIST_VIEWS = {
    "upcoming": _("Upcoming"),
    "arrivals": _("Arrivals today"),
    "in_house": _("In house"),
    "departures": _("Departures"),
    "all": _("All"),
}


@module_required("frontdesk")
def reservation_list(request):
    today = timezone.localdate()
    view = request.GET.get("view", "upcoming")
    qs = Reservation.objects.select_related("guest", "room", "room__room_type")
    if view == "arrivals":
        qs = qs.filter(status=Reservation.Status.BOOKED, arrival__lte=today, departure__gt=today).order_by(
            "room__number"
        )
    elif view == "in_house":
        qs = qs.filter(status=Reservation.Status.CHECKED_IN).order_by("room__number")
    elif view == "departures":
        qs = qs.filter(status=Reservation.Status.CHECKED_IN, departure__lte=today).order_by("room__number")
    elif view == "upcoming":
        qs = qs.filter(status=Reservation.Status.BOOKED, departure__gt=today).order_by("arrival", "room__number")
    else:
        view = "all"
    q = request.GET.get("q", "").strip()
    if q:
        cond = Q(guest__first_name__icontains=q) | Q(guest__last_name__icontains=q) | Q(guest__phone__icontains=q)
        cond |= Q(room__number=q) | Q(external_ref__icontains=q)
        code = q.upper().lstrip("R")
        if code.isdigit():
            cond |= Q(pk=int(code))
        qs = qs.filter(cond)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "frontdesk/reservation_list.html",
        {"page_obj": page, "object_list": page.object_list, "view": view, "views": LIST_VIEWS, "q": q, "today": today},
    )


@module_required("frontdesk")
def reservation_form(request, pk=None):
    reservation = get_object_or_404(Reservation, pk=pk) if pk else None
    if reservation and not reservation.is_active:
        messages.error(request, _("Closed or cancelled reservations cannot be changed."))
        return redirect("frontdesk:reservation_detail", pk=pk)

    initial = {}
    if not reservation:
        today = timezone.localdate()
        arrival = _parse_date(request.GET.get("arrival"), today)
        initial = {"arrival": arrival, "departure": arrival + timedelta(days=1), "adults": 2}
        if request.GET.get("room"):
            initial["room"] = request.GET["room"]
        if request.GET.get("guest"):
            initial["guest"] = request.GET["guest"]

    form = ReservationForm(request.POST or None, instance=reservation, initial=initial)
    if request.method == "POST" and form.is_valid():
        res = form.save(commit=False)
        try:
            if not res.pk:
                res.guest = form.get_guest()
            services.save_reservation(res, request.user)
        except ValidationError as e:
            for field, errs in e.message_dict.items():
                form.add_error(field if field in form.fields else None, errs)
        except BusinessError as e:
            form.add_error(None, str(e))
        else:
            messages.success(request, _("Reservation %(code)s saved.") % {"code": res.code})
            return redirect("frontdesk:reservation_detail", pk=res.pk)
    return render(request, "frontdesk/reservation_form.html", {"form": form, "object": reservation})


@module_required("frontdesk")
def reservation_detail(request, pk):
    res = get_object_or_404(Reservation.objects.select_related("guest", "room", "room__room_type"), pk=pk)
    folio, _created = Folio.objects.get_or_create(reservation=res)
    charges = folio.charges.select_related("outlet", "created_by").order_by("business_date", "id")
    payments = folio.payments.select_related("created_by").order_by("business_date", "id")
    pending_nights = 0
    if res.status == Reservation.Status.CHECKED_IN:
        pending_nights = max(0, max(res.nights, res.nights_to_charge()) - folio.accommodation_nights_posted())
    elif res.status == Reservation.Status.BOOKED:
        pending_nights = res.nights
    pending_amount = res.rate * pending_nights
    return render(
        request,
        "frontdesk/reservation_detail.html",
        {
            "r": res,
            "folio": folio,
            "charges": charges,
            "payments": payments,
            "pending_nights": pending_nights,
            "pending_amount": pending_amount,
            "expected_balance": folio.balance + pending_amount,
            "charge_form": ChargeForm(),
            "payment_form": PaymentForm(
                initial={"amount": max(folio.balance + pending_amount, Decimal("0")).quantize(Decimal("0.01")) or None}
            ),
            "today": timezone.localdate(),
        },
    )


def _action(request, pk, func, success_message, **kwargs):
    res = get_object_or_404(Reservation, pk=pk)
    try:
        func(res, request.user, **kwargs)
    except (BusinessError, ValidationError) as e:
        _business_error(request, e)
    else:
        messages.success(request, success_message % {"guest": res.guest, "room": res.room.number})
    return redirect(request.POST.get("next") or reverse("frontdesk:reservation_detail", args=[pk]))


@require_POST
@module_required("frontdesk")
def check_in(request, pk):
    return _action(request, pk, services.check_in, _("%(guest)s checked in to room %(room)s."))


@require_POST
@module_required("frontdesk")
def check_out(request, pk):
    allow_balance = request.POST.get("allow_balance") == "1" and request.user.is_manager
    return _action(
        request,
        pk,
        services.check_out,
        _("%(guest)s checked out. Room %(room)s sent to housekeeping."),
        allow_balance=allow_balance,
    )


@require_POST
@module_required("frontdesk")
def cancel(request, pk):
    no_show = request.POST.get("no_show") == "1"
    msg = _("Marked %(guest)s as a no-show.") if no_show else _("Reservation for %(guest)s cancelled.")
    return _action(request, pk, services.cancel, msg, no_show=no_show)


@require_POST
@module_required("frontdesk")
def add_charge(request, pk):
    res = get_object_or_404(Reservation, pk=pk)
    form = ChargeForm(request.POST)
    if form.is_valid():
        try:
            services.add_charge(res.folio, user=request.user, **form.cleaned_data)
            messages.success(request, _("Charge added."))
        except BusinessError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, _("Check the charge details."))
    return redirect(reverse("frontdesk:reservation_detail", args=[pk]) + "#folio")


@require_POST
@module_required("frontdesk")
def add_payment(request, pk):
    res = get_object_or_404(Reservation, pk=pk)
    form = PaymentForm(request.POST)
    if form.is_valid():
        try:
            services.add_payment(res.folio, user=request.user, **form.cleaned_data)
            messages.success(request, _("Payment recorded."))
        except BusinessError as e:
            messages.error(request, str(e))
    else:
        for errs in form.errors.values():
            for e in errs:
                messages.error(request, e)
    return redirect(reverse("frontdesk:reservation_detail", args=[pk]) + "#folio")


@require_POST
@module_required("frontdesk")
def void_entry(request, pk, kind, entry_id):
    res = get_object_or_404(Reservation, pk=pk)
    model = {"charge": Charge, "payment": Payment}.get(kind)
    if model is None:
        return redirect("frontdesk:reservation_detail", pk=pk)
    entry = get_object_or_404(model, pk=entry_id, folio__reservation=res)
    form = VoidForm(request.POST)
    try:
        if not form.is_valid():
            raise BusinessError(_("Give a reason for the void."))
        services.void_entry(entry, reason=form.cleaned_data["reason"], user=request.user)
        messages.success(request, _("Entry voided."))
    except BusinessError as e:
        messages.error(request, str(e))
    return redirect(reverse("frontdesk:reservation_detail", args=[pk]) + "#folio")


@module_required("frontdesk")
def invoice(request, pk):
    res = get_object_or_404(Reservation.objects.select_related("guest", "room"), pk=pk)
    folio, _created = Folio.objects.get_or_create(reservation=res)
    return render(
        request,
        "frontdesk/invoice.html",
        {
            "r": res,
            "folio": folio,
            "charges": folio.charges.active().order_by("business_date", "id"),
            "payments": folio.payments.active().order_by("business_date", "id"),
            "printed_at": timezone.localtime(),
        },
    )


# ---------- Guests ----------


@module_required("guests")
def guest_list(request):
    qs = Guest.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(email__icontains=q)
            | Q(document_number__icontains=q)
            | Q(company__icontains=q)
        )
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "frontdesk/guest_list.html", {"page_obj": page, "object_list": page.object_list, "q": q})


@module_required("guests")
def guest_detail(request, pk):
    guest = get_object_or_404(Guest, pk=pk)
    stays = guest.reservations.select_related("room").order_by("-arrival")
    return render(request, "frontdesk/guest_detail.html", {"guest": guest, "stays": stays})


@module_required("guests")
def guest_form(request, pk=None):
    guest = get_object_or_404(Guest, pk=pk) if pk else None
    form = GuestForm(request.POST or None, instance=guest)
    if request.method == "POST" and form.is_valid():
        guest = form.save()
        messages.success(request, _("Guest saved."))
        return redirect("frontdesk:guest_detail", pk=guest.pk)
    return render(request, "frontdesk/guest_form.html", {"form": form, "object": guest})


# ---------- Setup: rooms & room types (managers) ----------

SETUP_TABS = [("frontdesk:room_list", _("Rooms")), ("frontdesk:roomtype_list", _("Room types & rates"))]


class RoomList(CrudListView):
    model = Room
    queryset = Room.objects.select_related("room_type")
    title = _("Rooms & rates")
    singular = _("room")
    tabs = SETUP_TABS
    list_url_name = "frontdesk:room_list"
    create_url_name = "frontdesk:room_create"
    update_url_name = "frontdesk:room_edit"
    search_fields = ["number", "room_type__name"]
    columns = [
        ("number", _("Room"), "text"),
        ("room_type.name", _("Type"), "text"),
        ("floor", _("Floor"), "text"),
        ("hk_status", _("Status"), "choice"),
        ("out_of_order", _("Out of order"), "bool"),
        ("is_active", _("Active"), "bool"),
    ]


class RoomFormConfig:
    model = Room
    form_class = RoomForm
    title = _("Rooms & rates")
    singular = _("room")
    list_url_name = "frontdesk:room_list"


class RoomCreate(RoomFormConfig, CrudCreateView):
    pass


class RoomEdit(RoomFormConfig, CrudUpdateView):
    pass


class RoomTypeList(CrudListView):
    model = RoomType
    title = _("Rooms & rates")
    singular = _("room type")
    tabs = SETUP_TABS
    list_url_name = "frontdesk:roomtype_list"
    create_url_name = "frontdesk:roomtype_create"
    update_url_name = "frontdesk:roomtype_edit"
    columns = [
        ("name", _("Name"), "text"),
        ("code", _("Code"), "text"),
        ("base_rate", _("Nightly rate"), "money"),
        ("max_adults", _("Max adults"), "text"),
        ("max_children", _("Max children"), "text"),
        ("is_active", _("Active"), "bool"),
    ]


class RoomTypeFormConfig:
    model = RoomType
    form_class = RoomTypeForm
    title = _("Rooms & rates")
    singular = _("room type")
    list_url_name = "frontdesk:roomtype_list"


class RoomTypeCreate(RoomTypeFormConfig, CrudCreateView):
    pass


class RoomTypeEdit(RoomTypeFormConfig, CrudUpdateView):
    pass
