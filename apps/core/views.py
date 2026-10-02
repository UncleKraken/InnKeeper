from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.accounts.permissions import ModuleRequiredMixin, can_access, module_required
from apps.finance.models import Charge
from apps.frontdesk.models import Reservation, Room
from apps.housekeeping.models import HousekeepingTask, MaintenanceTicket
from apps.outlets.models import Order

from .models import AuditLog, HotelSettings


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
        open_qs = Order.objects.filter(status=Order.Status.OPEN).select_related("outlet", "table", "opened_by")
        ctx["open_orders"] = open_qs.count()
        ctx["open_order_list"] = [o for o in open_qs.order_by("opened_at")[:10] if o.outlet.user_can_use(user)]

    if can_access(user, "finance"):
        ctx["revenue_today"] = Charge.objects.active().filter(business_date=today).aggregate(t=Sum("amount"))["t"] or 0

    if user.is_manager and not HotelSettings.load().onboarding_dismissed:
        steps = onboarding_steps(user)
        if not all(s["done"] for s in steps):
            ctx["onboarding"] = steps
            ctx["onboarding_done"] = sum(1 for s in steps if s["done"])
            ctx["onboarding_total"] = len(steps)

    return render(request, "core/dashboard.html", ctx)


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


# ---------- Setup wizard ----------


@module_required("management")
def setup_wizard(request):
    from .forms import SetupForm
    from .setup import DEFAULTS_BY_TYPE, SetupAnswers, apply_setup

    hs = HotelSettings.load()
    if request.method == "POST":
        form = SetupForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            apply_setup(
                SetupAnswers(
                    business_type=d["business_type"],
                    name=d["name"],
                    language=d["language"],
                    address=d["address"],
                    tax_id=d["tax_id"],
                    phone=d["phone"],
                    email=d["email"],
                    currency=d["currency"],
                    vat_rate=d["vat_rate"],
                    modules=set(d["modules"]),
                    floors=d.get("floors") or 0,
                    rooms_per_floor=d.get("rooms_per_floor") or 0,
                    room_rate=d.get("room_rate") or Decimal("0"),
                    outlets=set(d["outlets"]),
                ),
                request.user,
            )
            response = redirect("core:setup_done")
            response.set_cookie("django_language", d["language"], max_age=365 * 24 * 3600, samesite="Lax")
            request.user.language = ""
            request.user.save(update_fields=["language"])
            return response
    else:
        current = []
        if hs.module_rooms:
            current.append("rooms")
        if hs.module_housekeeping:
            current.append("housekeeping")
        if hs.module_maintenance:
            current.append("maintenance")
        if hs.module_outlets:
            current.append("outlets")
        form = SetupForm(
            initial={
                "business_type": hs.business_type,
                "name": hs.name if hs.setup_completed else "",
                "language": hs.default_language,
                "address": hs.address,
                "tax_id": hs.tax_id,
                "phone": hs.phone,
                "email": hs.email,
                "currency": hs.currency,
                "vat_rate": hs.vat_rate,
                "modules": current,
                "outlets": sorted(DEFAULTS_BY_TYPE[hs.business_type]["outlets"]),
            }
        )
    defaults = {
        k: {"modules": sorted(v["modules"]), "outlets": sorted(v["outlets"])} for k, v in DEFAULTS_BY_TYPE.items()
    }
    from apps.frontdesk.models import Room
    from apps.outlets.models import Outlet

    return render(
        request,
        "core/setup.html",
        {
            "form": form,
            "defaults": defaults,
            "has_rooms": Room.objects.exists(),
            "existing_outlets": set(Outlet.objects.values_list("kind", flat=True)),
            "rerun": hs.setup_completed,
        },
    )


@module_required("management")
def setup_done(request):
    from apps.frontdesk.models import Room
    from apps.outlets.models import Outlet

    return render(
        request,
        "core/setup_done.html",
        {"rooms": Room.objects.count(), "outlets": Outlet.objects.filter(is_active=True)},
    )


# ---------- Help & getting started ----------


@login_required
def help_center(request):
    from django.utils.translation import get_language

    lang = "sq" if (get_language() or "sq").startswith("sq") else "en"
    return render(request, "help/help.html", {"guide": f"help/guide_{lang}.html"})


def onboarding_steps(user) -> list[dict]:
    """The manager's getting-started checklist, worked out from what already exists."""
    from django.urls import reverse

    from apps.accounts.models import User
    from apps.outlets.models import Item

    hs = HotelSettings.load()
    steps = [
        {"label": _("Set up your business"), "done": hs.setup_completed, "url": reverse("core:setup")},
        {
            "label": _("Add your staff"),
            "done": User.objects.filter(is_active=True).count() > 1,
            "url": reverse("accounts:staff_create"),
        },
    ]
    if hs.module_rooms:
        steps.append(
            {
                "label": _("Check your rooms and rates"),
                "done": Room.objects.exists(),
                "url": reverse("frontdesk:room_list"),
            }
        )
    if hs.module_outlets:
        steps.append(
            {"label": _("Fill in your menu"), "done": Item.objects.exists(), "url": reverse("outlets:item_list")}
        )
    steps += [
        {
            "label": _("Add your logo and receipt text"),
            "done": bool(hs.logo),
            "url": reverse("core:settings") + "?tab=receipts",
        },
        {
            "label": _("Download your first backup"),
            "done": AuditLog.objects.filter(action__startswith="backup.").exists(),
            "url": reverse("core:settings") + "?tab=backup",
        },
    ]
    return steps


@require_POST
@module_required("management")
def dismiss_onboarding(request):
    hs = HotelSettings.load()
    hs.onboarding_dismissed = True
    hs.save()
    return redirect("core:dashboard")
