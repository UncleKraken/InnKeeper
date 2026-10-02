from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.accounts.models import Role, User
from apps.accounts.permissions import module_required
from apps.core.exceptions import BusinessError
from apps.core.forms import DateInput, StyledFormMixin
from apps.frontdesk.models import Reservation, Room

from . import services
from .models import HousekeepingTask, MaintenanceTicket


class TaskForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HousekeepingTask
        fields = ["room", "kind", "assigned_to", "due_date", "notes"]
        widgets = {"due_date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = Room.objects.filter(is_active=True)
        self.fields["assigned_to"].queryset = User.objects.filter(is_active=True, role=Role.HOUSEKEEPING)


class TicketForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = MaintenanceTicket
        fields = ["title", "room", "location", "priority", "assigned_to", "blocks_room", "description"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = Room.objects.filter(is_active=True)
        self.fields["assigned_to"].queryset = User.objects.filter(
            is_active=True, role__in=[Role.MAINTENANCE, Role.MANAGER]
        )


@module_required("housekeeping")
def board(request):
    today = timezone.localdate()
    show = request.GET.get("show", "all")
    rooms = Room.objects.filter(is_active=True).select_related("room_type")
    if show == "dirty":
        rooms = rooms.filter(hk_status=Room.HKStatus.DIRTY)
    occupied = set(Reservation.objects.filter(status=Reservation.Status.CHECKED_IN).values_list("room_id", flat=True))
    arriving = set(
        Reservation.objects.filter(status=Reservation.Status.BOOKED, arrival=today).values_list("room_id", flat=True)
    )
    floors: dict[int, list] = {}
    for room in rooms:
        floors.setdefault(room.floor, []).append(
            {"room": room, "occupied": room.pk in occupied, "arriving": room.pk in arriving}
        )

    tasks = HousekeepingTask.objects.exclude(status=HousekeepingTask.Status.DONE).select_related("room", "assigned_to")
    if request.user.role == Role.HOUSEKEEPING and request.GET.get("mine") != "0":
        tasks = tasks.filter(assigned_to__in=[request.user]) | tasks.filter(assigned_to__isnull=True)
    staff = User.objects.filter(is_active=True, role=Role.HOUSEKEEPING)
    counts = {
        "dirty": Room.objects.filter(is_active=True, hk_status=Room.HKStatus.DIRTY).count(),
        "ooo": Room.objects.filter(is_active=True, out_of_order=True).count(),
        "occupied": len(occupied),
        "arriving": len(arriving),
    }
    return render(
        request,
        "housekeeping/board.html",
        {"floors": sorted(floors.items()), "tasks": tasks.distinct(), "staff": staff, "show": show, "counts": counts},
    )


@require_POST
@module_required("housekeeping")
def room_status(request, pk):
    room = get_object_or_404(Room, pk=pk)
    try:
        services.set_room_status(room, request.POST.get("status", ""), request.user)
    except BusinessError as e:
        messages.error(request, str(e))
    return redirect(request.POST.get("next") or "housekeeping:board")


@module_required("housekeeping")
def task_create(request):
    form = TaskForm(request.POST or None, initial={"room": request.GET.get("room")})
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        task.created_by = request.user
        task.save()
        messages.success(request, _("Task added."))
        return redirect("housekeeping:board")
    return render(request, "housekeeping/form.html", {"form": form, "title": _("New housekeeping task")})


@require_POST
@module_required("housekeeping")
def task_advance(request, pk):
    task = get_object_or_404(HousekeepingTask, pk=pk)
    try:
        services.advance_task(task, request.user)
    except BusinessError as e:
        messages.error(request, str(e))
    return redirect(request.POST.get("next") or "housekeeping:board")


@require_POST
@module_required("housekeeping")
def task_assign(request, pk):
    task = get_object_or_404(HousekeepingTask, pk=pk)
    staff_id = request.POST.get("assigned_to") or None
    if staff_id and not User.objects.filter(pk=staff_id, is_active=True).exists():
        staff_id = None
    task.assigned_to_id = staff_id
    task.save(update_fields=["assigned_to"])
    return redirect("housekeeping:board")


# ---------- Maintenance ----------


@module_required("maintenance")
def ticket_list(request):
    show = request.GET.get("show", "open")
    qs = MaintenanceTicket.objects.select_related("room", "assigned_to", "reported_by")
    if show == "open":
        qs = qs.exclude(status=MaintenanceTicket.Status.RESOLVED)
    elif show == "resolved":
        qs = qs.filter(status=MaintenanceTicket.Status.RESOLVED).order_by("-resolved_at")
    if request.GET.get("mine") == "1":
        qs = qs.filter(assigned_to=request.user)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(
        request, "housekeeping/ticket_list.html", {"page_obj": page, "object_list": page.object_list, "show": show}
    )


@module_required("maintenance")
def ticket_form(request, pk=None):
    ticket = get_object_or_404(MaintenanceTicket, pk=pk) if pk else None
    form = TicketForm(request.POST or None, instance=ticket, initial={"room": request.GET.get("room")})
    if request.method == "POST" and form.is_valid():
        try:
            services.save_ticket(form.save(commit=False), request.user)
        except BusinessError as e:
            form.add_error("room", str(e))
        else:
            messages.success(request, _("Maintenance ticket saved."))
            return redirect("housekeeping:ticket_list")
    title = ticket.title if ticket else _("Report a problem")
    return render(request, "housekeeping/form.html", {"form": form, "title": title, "ticket": ticket})


@require_POST
@module_required("maintenance")
def ticket_status(request, pk):
    ticket = get_object_or_404(MaintenanceTicket, pk=pk)
    action = request.POST.get("action")
    try:
        if action == "start" and ticket.status == MaintenanceTicket.Status.OPEN:
            ticket.status = MaintenanceTicket.Status.IN_PROGRESS
            if ticket.assigned_to_id is None:
                ticket.assigned_to = request.user
            services.save_ticket(ticket, request.user)
        elif action == "resolve":
            services.resolve_ticket(ticket, request.user, request.POST.get("resolution", ""))
            messages.success(request, _("Ticket resolved."))
    except BusinessError as e:
        messages.error(request, str(e))
    return redirect("housekeeping:ticket_list")
