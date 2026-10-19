"""
The owner's daily summary: one short email with how yesterday went.

Sent at the hour chosen in Settings → Email for the business day before (so a night bar's
Saturday night arrives on Sunday morning), and again right after a day close.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.core.businessday import business_date, day_range
from apps.core.models import HotelSettings

from .models import ZERO, Charge, DayClose, Shift, net

log = logging.getLogger(__name__)


def build(day: date) -> dict:
    from apps.outlets.models import Order, OrderLine

    from .reports import day_summary

    hs = HotelSettings.load()
    s = day_summary(day)
    since, until = day_range(day)
    week_ago = Charge.objects.period(day - timedelta(days=7)).revenue().aggregate(t=net("amount", day - timedelta(days=7)))["t"]
    week_ago = week_ago or ZERO
    change = None
    if week_ago:
        change = ((s["revenue"] - week_ago) / week_ago * 100).quantize(Decimal("1"))
    top = (
        OrderLine.objects.filter(order__status=Order.Status.CLOSED, order__closed_at__gte=since, order__closed_at__lt=until)
        .values("name")
        .annotate(qty=Sum("quantity"), total=Sum(F("quantity") * F("unit_price")))
        .order_by("-total")[:5]
    )
    voided = Charge.objects.filter(voided_at__gte=since, voided_at__lt=until)
    shifts = [
        sh
        for sh in Shift.objects.filter(closed_at__gte=since, closed_at__lt=until).select_related("user")
        if sh.difference
    ]
    ctx = {
        "day": day,
        "s": s,
        "close": DayClose.objects.filter(business_date=day).first(),
        "week_ago": week_ago,
        "change": change,
        "top": list(top),
        "tips": s["tips_cash"] + s["tips_paid_out"],
        "voided_count": voided.count(),
        "voided_total": voided.aggregate(t=Sum("amount"))["t"] or ZERO,
        "shift_differences": shifts,
        "warnings": _warnings(),
        "link": f"{hs.public_url.rstrip('/')}/finance/day-close/?date={day.isoformat()}" if hs.public_url else "",
    }
    ctx.update(_rooms(day))
    return ctx


def _rooms(day: date) -> dict:
    from apps.frontdesk.models import Reservation, Room

    rooms = Room.objects.filter(is_active=True).count()
    if not rooms:
        return {"rooms": 0}
    stayed = Reservation.objects.filter(
        arrival__lte=day,
        departure__gt=day,
        status__in=[Reservation.Status.CHECKED_IN, Reservation.Status.CHECKED_OUT],
    ).count()
    next_day = day + timedelta(days=1)
    return {
        "rooms": rooms,
        "occupied": stayed,
        "occupancy": round(stayed * 100 / rooms),
        "arrivals": Reservation.objects.filter(arrival=next_day, status=Reservation.Status.BOOKED).count(),
        "departures": Reservation.objects.filter(departure=next_day, status=Reservation.Status.CHECKED_IN).count(),
    }


def _warnings() -> list[str]:
    hs = HotelSettings.load()
    out = []
    try:
        from apps.inventory.models import StockItem

        low = sum(1 for i in StockItem.objects.filter(is_active=True, min_level__gt=0) if i.is_low)
        if low:
            out.append(ngettext("%(n)s stock item is running low.", "%(n)s stock items are running low.", low) % {"n": low})
    except Exception:  # inventory is optional for the summary
        pass
    if hs.fiscal_on:
        from apps.fiscal.models import FiscalDocument

        stuck = FiscalDocument.objects.exclude(status=FiscalDocument.Status.REGISTERED).count()
        if stuck:
            out.append(
                ngettext(
                    "%(n)s receipt is not registered with the tax authority yet.",
                    "%(n)s receipts are not registered with the tax authority yet.",
                    stuck,
                )
                % {"n": stuck}
            )
    from apps.staff.models import TimeEntry

    forgot = [e for e in TimeEntry.objects.filter(clock_out__isnull=True).select_related("user") if e.forgotten]
    if forgot:
        out.append(_("Still clocked in for more than 16 hours: %(names)s.") % {"names": ", ".join(str(e.user) for e in forgot)})
    if hs.sync_enabled and hs.sync_last_error:
        out.append(_("Automatic copies are not working: %(e)s") % {"e": hs.sync_last_error})
    return out


def has_activity(ctx: dict) -> bool:
    s = ctx["s"]
    return bool(s["revenue"] or s["received"] or ctx["close"] or ctx["voided_count"])


def send(day: date, *, force: bool = False) -> bool:
    """Email the summary of `day`. Returns True when it was sent."""
    from apps.core import email

    hs = HotelSettings.load()
    to = hs.summary_recipients
    if not to or not hs.email_configured:
        return False
    ctx = build(day)
    if not force and not has_activity(ctx):
        HotelSettings.objects.filter(pk=hs.pk).update(summary_sent_for=day)  # a closed day: nothing to report
        return False
    from apps.core.templatetags.innkeeper import money

    subject = _("%(name)s · %(day)s · sales %(total)s") % {
        "name": hs.name,
        "day": day.strftime("%d.%m.%Y"),
        "total": money(ctx["s"]["revenue"]),
    }
    ok = email.send(to, subject, "finance/email_summary.html", ctx)
    if ok and (hs.summary_sent_for is None or day >= hs.summary_sent_for):
        HotelSettings.objects.filter(pk=hs.pk).update(summary_sent_for=day)
        hs.summary_sent_for = day
    return ok


def run(now=None) -> bool:
    """Called every few minutes by the background jobs: sends yesterday's summary once, at the chosen hour."""
    hs = HotelSettings.load()
    if not hs.summary_recipients or not hs.email_configured:
        return False
    now = now or timezone.now()
    day = business_date(now) - timedelta(days=1)
    if hs.summary_sent_for and hs.summary_sent_for >= day:
        return False
    if timezone.localtime(now).hour < hs.summary_hour:
        return False
    try:
        return send(day)
    except Exception as e:  # never stop the other background jobs
        log.warning("Daily summary failed: %s", e)
        return False
