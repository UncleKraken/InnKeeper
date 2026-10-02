from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic import ListView

from apps.accounts.permissions import ModuleRequiredMixin, can_access, module_required
from apps.finance.models import Charge
from apps.frontdesk.models import Reservation, Room
from apps.housekeeping.models import HousekeepingTask, MaintenanceTicket
from apps.outlets.models import Order

from .forms import StyledFormMixin, TimeInput
from .models import AuditLog, HotelSettings, audit


def health(request):
    """Used by Docker / uptime monitors."""
    return JsonResponse({"status": "ok"})


@login_required
def dashboard(request):
    user = request.user
    today = timezone.localdate()
    ctx = {"today": today}

    if can_access(user, "frontdesk"):
        rooms_total = Room.objects.filter(is_active=True).count()
        in_house = Reservation.objects.filter(status=Reservation.Status.CHECKED_IN)
        ctx.update(
            arrivals=Reservation.objects.filter(
                status=Reservation.Status.BOOKED, arrival__lte=today, departure__gt=today
            )
            .select_related("guest", "room")
            .order_by("arrival", "room__number"),
            departures=in_house.filter(departure__lte=today).select_related("guest", "room").order_by("room__number"),
            in_house_count=in_house.count(),
            rooms_total=rooms_total,
            occupancy=round(in_house.count() * 100 / rooms_total) if rooms_total else 0,
            upcoming=Reservation.objects.filter(
                status=Reservation.Status.BOOKED, arrival__gt=today, arrival__lte=today + timedelta(days=7)
            ).count(),
        )

    if can_access(user, "housekeeping"):
        ctx["dirty_rooms"] = Room.objects.filter(is_active=True, hk_status=Room.HKStatus.DIRTY).count()
        tasks = HousekeepingTask.objects.exclude(status=HousekeepingTask.Status.DONE).select_related(
            "room", "assigned_to"
        )
        if user.role == "housekeeping":
            tasks = tasks.filter(assigned_to__in=[user, None])
        ctx["hk_tasks"] = tasks[:8]

    if can_access(user, "maintenance"):
        ctx["open_tickets"] = MaintenanceTicket.objects.exclude(status=MaintenanceTicket.Status.RESOLVED).count()
        ctx["ooo_rooms"] = Room.objects.filter(is_active=True, out_of_order=True).count()

    if can_access(user, "outlets"):
        ctx["open_orders"] = Order.objects.filter(status=Order.Status.OPEN).count()

    if can_access(user, "finance"):
        ctx["revenue_today"] = Charge.objects.active().filter(business_date=today).aggregate(t=Sum("amount"))["t"] or 0

    return render(request, "core/dashboard.html", ctx)


def _settings_form_class():
    from django import forms

    class Form(StyledFormMixin, forms.ModelForm):
        full_width_fields = ("address",)

        class Meta:
            model = HotelSettings
            fields = [
                "name",
                "legal_name",
                "tax_id",
                "address",
                "phone",
                "email",
                "currency",
                "currency_symbol",
                "vat_rate",
                "check_in_time",
                "check_out_time",
                "invoice_footer",
            ]
            widgets = {"check_in_time": TimeInput(), "check_out_time": TimeInput()}

    return Form


@module_required("management")
def hotel_settings(request):
    form = _settings_form_class()(request.POST or None, instance=HotelSettings.load())
    if request.method == "POST" and form.is_valid():
        form.save()
        audit(request.user, "settings.save", form.instance.name, form.instance)
        messages.success(request, _("Settings saved."))
        return redirect("core:settings")
    return render(request, "core/settings.html", {"form": form})


class AuditLogView(ModuleRequiredMixin, ListView):
    module = "management"
    model = AuditLog
    paginate_by = 100
    template_name = "core/audit_log.html"

    def get_queryset(self):
        qs = AuditLog.objects.select_related("user")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(description__icontains=q) | qs.filter(action__icontains=q)
        return qs
