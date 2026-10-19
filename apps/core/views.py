from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.accounts.permissions import ModuleRequiredMixin, can_access, module_required
from apps.finance.models import Charge, net
from apps.frontdesk.models import Reservation, Room
from apps.housekeeping.models import HousekeepingTask, MaintenanceTicket
from apps.outlets.models import Order

from .models import AuditLog, HotelSettings


def health(request):
    """Used by Docker / uptime monitors."""
    from apps import __version__

    return JsonResponse({"status": "ok", "version": __version__})


@module_required("management")
def update_page(request):
    from apps import __version__

    from . import updates

    if request.GET.get("check"):
        from django.core.cache import cache

        cache.delete(updates.CACHE_KEY)
    info = updates.latest_release()
    newer = updates.update_available()
    return render(
        request,
        "core/update.html",
        {
            "current": __version__,
            "info": info,
            "newer": newer,
            "can_install": updates.can_install() and bool(newer and newer.get("installer")),
            "state": updates.STATE,
        },
    )


@require_POST
@module_required("management")
def update_install(request):
    from . import updates

    newer = updates.update_available()
    if not (updates.can_install() and newer and newer.get("installer")):
        return redirect("core:update")
    from apps.core.models import audit

    audit(request.user, "app.update", newer["version"])
    updates.start_install(newer)
    return redirect("core:update")


@module_required("management")
def update_status(request):
    from apps import __version__

    from . import updates

    return JsonResponse({**updates.STATE, "current": __version__})


@login_required
def dashboard(request):
    user = request.user
    if user.role == "kitchen" and not user.is_manager:
        return redirect("outlets:board_home")
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
            online_requests=Reservation.objects.filter(status=Reservation.Status.BOOKED, confirmed=False).count(),
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
        from apps.core.businessday import business_date

        day = business_date()  # a night bar at 01:30 still sees tonight's takings
        ctx["revenue_today"] = Charge.objects.period(day).revenue().aggregate(t=net("amount", day))["t"] or 0
        if day.day <= 5 and HotelSettings.load().tourist_tax_enabled:
            from datetime import timedelta as _td

            from apps.finance import tourist_tax

            last = (day.replace(day=1) - _td(days=1)).replace(day=1)
            due = tourist_tax.report(last, day.replace(day=1) - _td(days=1))
            if due["total"]:
                ctx["tourist_tax_due"] = {**due, "month": last.strftime("%Y-%m")}

    if can_access(user, "frontdesk") and HotelSettings.load().channex_enabled:
        from datetime import timedelta as _td

        from apps.frontdesk.models import ChannelBooking

        ctx["channel_problems"] = (
            ChannelBooking.objects.exclude(problem="").filter(updated_at__gte=timezone.now() - _td(days=14)).count()
        )

    if can_access(user, "finance") and HotelSettings.load().fiscal_on:
        from apps.fiscal.models import FiscalDocument
        from apps.fiscal.services import overdue

        ctx["fiscal_failed"] = FiscalDocument.objects.filter(status=FiscalDocument.Status.FAILED).count()
        ctx["fiscal_overdue"] = overdue()
        from apps.fiscal.services import unfiscalized

        ctx["fiscal_missing"] = len(unfiscalized())
        hs = HotelSettings.load()
        if hs.fiscal_certificate:
            from apps.fiscal.signing import Certificate, CertificateError

            try:
                expires = Certificate.from_settings(hs).not_after
            except CertificateError:
                ctx["fiscal_cert_problem"] = True
            else:
                days = (expires - timezone.now()).days
                if days < 30:
                    ctx["fiscal_cert_days"] = max(days, 0)

    if user.is_manager:
        from . import sync

        ctx["sync_status"] = sync.status()

    if can_access(user, "inventory"):
        from apps.inventory.views import low_stock_count

        ctx["low_stock"] = low_stock_count()

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
                    vat_rate=d["vat_rate"] or Decimal("0"),
                    tax_status=d["tax_status"],
                    modules=set(d["modules"]),
                    floors=d.get("floors") or 0,
                    rooms_per_floor=d.get("rooms_per_floor") or 0,
                    room_rate=d.get("room_rate") or Decimal("0"),
                    outlets=set(d["outlets"]),
                    day_ends_at=d.get("day_ends_at"),
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
                "vat_rate": hs.vat_rate if hs.charges_vat else Decimal("20"),
                "tax_status": hs.tax_status,
                "modules": current,
                "outlets": sorted(DEFAULTS_BY_TYPE[hs.business_type]["outlets"]),
                "day_ends_at": hs.day_ends_at,
            }
        )
    defaults = {
        k: {"modules": sorted(v["modules"]), "outlets": sorted(v["outlets"]), "day_ends_at": v["day_ends_at"]}
        for k, v in DEFAULTS_BY_TYPE.items()
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
            "can_sample": not hs.setup_completed and _sample_empty(),
        },
    )


@require_POST
@module_required("management")
def sample_load(request):
    from . import sample
    from .exceptions import BusinessError

    try:
        sample.load(request.user)
    except BusinessError:
        messages.error(request, _("Sample data can only be added to an empty InnKeeper."))
        return redirect("core:setup")
    messages.success(request, _("Sample data added. Look around: nothing here is real. When you're ready, use the banner at the top to start with your own business."))
    return redirect("core:dashboard")


@module_required("management")
def sample_remove(request):
    from . import sample
    from .exceptions import BusinessError

    if not HotelSettings.load().demo_data:
        return redirect("core:dashboard")
    if request.method == "POST":
        if request.POST.get("confirm") != "1":
            messages.error(request, _("Tick the box to confirm."))
        else:
            try:
                sample.remove(request.user)
            except BusinessError:
                return redirect("core:dashboard")
            messages.success(request, _("The sample data is gone. Now set up your own business."))
            return redirect("core:setup")
    return render(request, "core/sample_remove.html")


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
            "label": _("Keep a copy of your data on a USB drive or in the cloud"),
            "done": bool(hs.sync_enabled and hs.sync_last_at),
            "url": reverse("core:settings") + "?tab=backup#sync",
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


def _sample_empty() -> bool:
    from . import sample

    return sample.is_empty()
