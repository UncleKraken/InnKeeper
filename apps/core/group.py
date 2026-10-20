"""
Group overview: one owner, several businesses.

Each business keeps its own InnKeeper and its own data (separate tills, staff, cash and tax
registration, as the law and the accountant expect). A business can share a short, read-only summary
with a secret key (Settings → Group overview). The owner's InnKeeper lists the other businesses with
their address and key and shows them all on one page: today's sales, the month so far, money received,
rooms, open bills, who is at work and anything that needs attention. No guest or staff names leave a
business, and the key can't change anything.

The other computers must be reachable from the owner's: Tailscale (private, recommended) or the public
address of the Cloudflare Tunnel.
"""

import hmac
import json
import secrets
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.cache import cache
from django.db.models import F, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required

from .forms import StyledFormMixin
from .models import GroupMember, HotelSettings, audit

TIMEOUT = 8
ZERO = Decimal("0.00")


# ---------- What a business shares ----------


def snapshot() -> dict:
    from apps import __version__
    from apps.finance.models import Charge, DayClose, Payment, net
    from apps.finance.summary import _warnings
    from apps.outlets.models import Order, OrderLine
    from apps.staff.models import TimeEntry

    from .businessday import business_date

    hs = HotelSettings.load()
    day = business_date()
    first = day.replace(day=1)

    def sales(start, end=None):
        end = end or start
        return Charge.objects.period(start, end).revenue().aggregate(t=net("amount", start, end))["t"] or ZERO

    received = (
        Payment.objects.period(day).exclude(method=Payment.Method.VOUCHER).aggregate(t=net("amount", day))["t"] or ZERO
    )
    open_orders = Order.objects.filter(status=Order.Status.OPEN)
    open_total = (
        OrderLine.objects.filter(order__in=open_orders).aggregate(t=Sum(F("quantity") * F("unit_price")))["t"] or ZERO
    )
    data = {
        "name": hs.name,
        "version": __version__,
        "currency": hs.currency,
        "symbol": hs.currency_symbol,
        "date": day.isoformat(),
        "sales_today": str(sales(day)),
        "sales_yesterday": str(sales(day - timedelta(days=1))),
        "sales_month": str(sales(first, day)),
        "received_today": str(received),
        "open_bills": open_orders.count(),
        "open_bills_total": str(open_total),
        "at_work": TimeEntry.objects.filter(clock_out__isnull=True).count(),
        "warnings": [str(w) for w in _warnings()],
        "last_day_close": (DayClose.objects.order_by("-business_date").values_list("business_date", flat=True).first() or ""),
    }
    if data["last_day_close"]:
        data["last_day_close"] = data["last_day_close"].isoformat()
    if hs.module_rooms:
        from apps.frontdesk.models import Reservation, Room

        rooms = Room.objects.filter(is_active=True).count()
        in_house = Reservation.objects.filter(status=Reservation.Status.CHECKED_IN).count()
        data["rooms"] = {
            "total": rooms,
            "in_house": in_house,
            "occupancy": round(in_house * 100 / rooms) if rooms else 0,
            "arrivals": Reservation.objects.filter(arrival=day, status=Reservation.Status.BOOKED).count(),
            "departures": Reservation.objects.filter(departure=day, status=Reservation.Status.CHECKED_IN).count(),
        }
    return data


def shared_summary(request):
    """GET /group/summary/ with "Authorization: Bearer <key>": the snapshot, read-only."""
    hs = HotelSettings.load()
    key = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not hs.group_token:
        raise Http404
    ip = request.META.get("REMOTE_ADDR", "")
    tries = f"innkeeper:group-fail:{ip}"
    if cache.get(tries, 0) >= 20:
        return JsonResponse({"error": "too many attempts"}, status=429)
    if not key or not hmac.compare_digest(key, hs.group_token):
        try:
            cache.incr(tries)
        except ValueError:
            cache.set(tries, 1, 900)
        return JsonResponse({"error": "wrong key"}, status=403)
    return JsonResponse(snapshot())


# ---------- The owner's page ----------


def fetch(member: GroupMember) -> dict:
    url = member.url.rstrip("/") + "/group/summary/"
    if not url.startswith(("http://", "https://")):
        return {"error": _("The address must start with http:// or https://")}
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {member.token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (owner-entered address)
            data = json.loads(r.read(200_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return {"error": _("The sharing key is wrong. Copy it again from that business.")}
        if e.code == 404:
            return {"error": _("That business is not sharing its summary (Settings → Group overview), or it runs an older InnKeeper.")}
        return {"error": _("The other InnKeeper answered with an error (%(code)s).") % {"code": e.code}}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"error": _("Not reachable. Is that computer on, with InnKeeper open and Tailscale connected?")}
    except ValueError:
        return {"error": _("That address is not an InnKeeper.")}
    if not isinstance(data, dict) or "sales_today" not in data:
        return {"error": _("That address is not an InnKeeper.")}
    for k in ("sales_today", "sales_yesterday", "sales_month", "received_today", "open_bills_total"):
        try:
            data[k] = Decimal(str(data.get(k, "0")))
        except Exception:
            data[k] = ZERO
    return data


def _local() -> dict:
    data = snapshot()
    for k in ("sales_today", "sales_yesterday", "sales_month", "received_today", "open_bills_total"):
        data[k] = Decimal(data[k])
    return data


@module_required("management")
def overview(request):
    members = list(GroupMember.objects.all())
    cards = [{"member": None, "data": _local(), "here": True}]
    if members:
        refresh = request.GET.get("refresh") == "1"
        key = "innkeeper:group:" + ",".join(f"{m.pk}:{m.url}" for m in members)
        results = None if refresh else cache.get(key)
        if results is None:
            with ThreadPoolExecutor(max_workers=min(8, len(members))) as pool:
                results = list(pool.map(fetch, members))  # network only: no database work in the threads
            ok = [m.pk for m, d in zip(members, results) if "error" not in d]
            GroupMember.objects.filter(pk__in=ok).update(last_ok_at=timezone.now())
            cache.set(key, results, 60)
        cards += [{"member": m, "data": d, "here": False} for m, d in zip(members, results)]
    totals = {}
    for c in cards:
        d = c["data"]
        if "error" in d:
            continue
        t = totals.setdefault(d.get("symbol") or d.get("currency") or "", {"sales_today": ZERO, "sales_month": ZERO, "received_today": ZERO, "open_bills_total": ZERO, "n": 0})
        for k in ("sales_today", "sales_month", "received_today", "open_bills_total"):
            t[k] += d[k]
        t["n"] += 1
    return render(
        request,
        "core/group.html",
        {"cards": cards, "totals": totals if len(cards) > 1 else {}, "members": members},
    )


class MemberForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = GroupMember
        fields = ["name", "url", "token", "sort_order"]
        widgets = {"token": forms.PasswordInput(render_value=True, attrs={"autocomplete": "off"})}

    def clean_url(self):
        url = self.cleaned_data["url"].strip().rstrip("/")
        if url.endswith("/group/summary"):
            url = url[: -len("/group/summary")]
        return url


@module_required("management")
def member_form(request, pk=None):
    member = get_object_or_404(GroupMember, pk=pk) if pk else None
    form = MemberForm(request.POST or None, instance=member)
    if request.method == "POST":
        if request.POST.get("delete") == "1" and member:
            audit(request.user, "group.remove", member.name)
            member.delete()
            messages.success(request, _("Removed from the group overview."))
            return redirect("core:group")
        if form.is_valid():
            m = form.save()
            audit(request.user, "group.save", m.name, m)
            result = fetch(m)
            if "error" in result:
                messages.warning(request, _("Saved, but: %(error)s") % {"error": result["error"]})
            else:
                messages.success(request, _("Connected to %(name)s.") % {"name": result.get("name") or m.name})
            return redirect("core:group")
    return render(request, "core/group_member_form.html", {"form": form, "member": member})


@require_POST
@module_required("management")
def sharing(request):
    """Create a new sharing key, or stop sharing."""
    hs = HotelSettings.load()
    if request.POST.get("on") == "1":
        hs.group_token = secrets.token_urlsafe(32)
        messages.success(request, _("New sharing key created. Paste it in the owner's InnKeeper; an older key stops working."))
        audit(request.user, "group.share_on", hs.name)
    else:
        hs.group_token = ""
        messages.success(request, _("This business no longer shares its summary."))
        audit(request.user, "group.share_off", hs.name)
    hs.save(update_fields=["group_token"])
    return redirect("/settings/?tab=group")
