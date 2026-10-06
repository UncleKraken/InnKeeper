"""Kitchen and bar screens: live tickets per station, and the waiter's 'ready to serve' signals."""

import hashlib

from django.contrib import messages
from django.db.models import Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required

from . import services
from .models import KitchenTicket, Order, OrderLine, Station


@module_required("kitchen")
def board_home(request):
    stations = list(Station.objects.filter(is_active=True))
    if len(stations) == 1:
        return redirect("outlets:board", pk=stations[0].pk)
    counts = {
        s.pk: KitchenTicket.objects.filter(
            station=s, status__in=[KitchenTicket.Status.NEW, KitchenTicket.Status.PREPARING]
        ).count()
        for s in stations
    }
    return render(request, "outlets/board_home.html", {"stations": [(s, counts[s.pk]) for s in stations]})


def _board_tickets(station: Station):
    lines = Prefetch("lines", queryset=OrderLine.objects.order_by("id"))
    qs = (
        KitchenTicket.objects.filter(station=station, status__in=KitchenTicket.ON_BOARD)
        .select_related("order__table", "order__outlet", "sent_by")
        .prefetch_related(lines)
        .order_by("sent_at", "id")
    )
    now = timezone.now()
    tickets = []
    for t in qs:
        minutes = int((now - t.sent_at).total_seconds() // 60)
        tickets.append({"t": t, "minutes": minutes, "late": minutes >= 20, "slow": 10 <= minutes < 20})
    return tickets


@module_required("kitchen")
def board(request, pk):
    station = get_object_or_404(Station, pk=pk, is_active=True)
    return render(
        request,
        "outlets/board.html",
        {"station": station, "stations": Station.objects.filter(is_active=True), "tickets": _board_tickets(station)},
    )


@module_required("kitchen")
def board_tickets(request, pk):
    """The ticket area only, refreshed by the screen every few seconds."""
    station = get_object_or_404(Station, pk=pk, is_active=True)
    tickets = _board_tickets(station)
    html = render(request, "outlets/_board_tickets.html", {"station": station, "tickets": tickets}).content
    response = HttpResponse(html)
    response["X-New-Tickets"] = ",".join(str(x["t"].pk) for x in tickets if x["t"].status == KitchenTicket.Status.NEW)
    return response


@require_POST
@module_required("kitchen")
def ticket_status(request, ticket_id):
    ticket = get_object_or_404(KitchenTicket, pk=ticket_id)
    status = request.POST.get("status", "")
    if status in KitchenTicket.Status.values:
        services.set_ticket_status(ticket, status, user=request.user)
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"ok": True})
    return redirect("outlets:board", pk=ticket.station_id)


@require_POST
@module_required("kitchen")
def recall(request, pk):
    """Bring back the last ticket that was cleared from this screen (a mis-tap)."""
    last = (
        KitchenTicket.objects.filter(station_id=pk, status=KitchenTicket.Status.SERVED, served_at__isnull=False)
        .order_by("-served_at")
        .first()
    )
    if last:
        services.set_ticket_status(last, KitchenTicket.Status.READY, user=request.user)
    else:
        messages.info(request, _("Nothing to bring back."))
    return redirect("outlets:board", pk=pk)


@require_POST
@module_required("outlets")
def serve_ready(request, order_id):
    """Waiter took the ready dishes to the table."""
    order = get_object_or_404(Order, pk=order_id)
    for t in order.tickets.filter(status=KitchenTicket.Status.READY):
        services.set_ticket_status(t, KitchenTicket.Status.SERVED, user=request.user)
    nxt = request.POST.get("next", "")
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect("outlets:order", pk=order.pk)


@module_required("outlets")
def floor_signature(request, pk):
    """A short fingerprint of an outlet's open orders, so the table plan can refresh itself when something changes."""
    orders = Order.objects.filter(outlet_id=pk, status=Order.Status.OPEN).values_list("pk", "table_id")
    ready = KitchenTicket.objects.filter(order__outlet_id=pk, status=KitchenTicket.Status.READY).values_list(
        "pk", flat=True
    )
    lines = OrderLine.objects.filter(order__outlet_id=pk, order__status=Order.Status.OPEN).values_list("pk", "quantity")
    raw = f"{sorted(orders)}|{sorted(ready)}|{sorted(lines)}"
    return JsonResponse({"sig": hashlib.sha1(raw.encode()).hexdigest()[:16]})
