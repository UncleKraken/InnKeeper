"""Clocking in and out, and comparing the schedule with the hours actually worked."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import BusinessError
from apps.core.models import audit

from .models import ScheduledShift, TimeEntry

LATE_AFTER = timedelta(minutes=10)


def open_entry(user) -> TimeEntry | None:
    return TimeEntry.objects.filter(user=user, clock_out__isnull=True).first()


def _position(user):
    profile = getattr(user, "employee", None)
    return profile.position if profile is not None else None


@transaction.atomic
def clock_in(user, *, source: str = TimeEntry.Source.WEB, when=None) -> TimeEntry:
    if not user.is_active:
        raise BusinessError(_("This account is not active."))
    if open_entry(user):
        raise BusinessError(_("%(name)s is already clocked in.") % {"name": user})
    try:
        with transaction.atomic():
            entry = TimeEntry.objects.create(
                user=user, clock_in=when or timezone.now(), source=source, position=_position(user)
            )
    except IntegrityError:  # a double tap: the first one already clocked in
        raise BusinessError(_("%(name)s is already clocked in.") % {"name": user})
    audit(user, "staff.clock_in", f"{user} {timezone.localtime(entry.clock_in):%H:%M}", entry)
    return entry


@transaction.atomic
def clock_out(user, *, when=None) -> TimeEntry:
    entry = TimeEntry.objects.select_for_update().filter(user=user, clock_out__isnull=True).first()
    if entry is None:
        raise BusinessError(_("%(name)s is not clocked in.") % {"name": user})
    entry.clock_out = max(when or timezone.now(), entry.clock_in)
    entry.save(update_fields=["clock_out"])
    audit(user, "staff.clock_out", f"{user} {timezone.localtime(entry.clock_out):%H:%M} ({entry.hours} h)", entry)
    return entry


def toggle(user, *, source: str = TimeEntry.Source.WEB) -> tuple[str, TimeEntry]:
    if open_entry(user):
        return "out", clock_out(user)
    return "in", clock_in(user, source=source)


def working_now():
    return (
        TimeEntry.objects.filter(clock_out__isnull=True)
        .select_related("user", "position")
        .order_by("clock_in")
    )


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, start + timedelta(days=1)


def attendance(start: date, end: date, users=None) -> list[dict]:
    """Per person: planned hours, worked hours, late arrivals, missing clock-outs, the entries and shifts."""
    since, _x = day_bounds(start)
    _y, until = day_bounds(end)
    entries = TimeEntry.objects.filter(clock_in__gte=since, clock_in__lt=until).select_related("user", "position")
    shifts = ScheduledShift.objects.filter(date__range=(start, end)).select_related("user", "position")
    if users is not None:
        entries = entries.filter(user__in=users)
        shifts = shifts.filter(user__in=users)
    by_user: dict = defaultdict(lambda: {"entries": [], "shifts": []})
    for e in entries:
        by_user[e.user]["entries"].append(e)
    for s in shifts:
        by_user[s.user]["shifts"].append(s)
    rows = []
    for user, d in by_user.items():
        entries_ = sorted(d["entries"], key=lambda e: e.clock_in)
        shifts_ = sorted(d["shifts"], key=lambda s: s.starts_at)
        late = 0
        no_show = 0
        for s in shifts_:
            first = next((e for e in entries_ if s.starts_at - timedelta(hours=3) <= e.clock_in < s.ends_at), None)
            if first is None:
                if s.ends_at < timezone.now():
                    no_show += 1
            elif first.clock_in > s.starts_at + LATE_AFTER:
                late += 1
        worked = sum(e.minutes for e in entries_ if e.clock_out)
        planned = sum(s.minutes for s in shifts_)
        rows.append(
            {
                "user": user,
                "entries": entries_,
                "shifts": shifts_,
                "worked": _h(worked),
                "planned": _h(planned),
                "difference": _h(worked - planned) if planned else None,
                "late": late,
                "no_show": no_show,
                "missing_out": sum(1 for e in entries_ if e.forgotten),
                "days": len({timezone.localtime(e.clock_in).date() for e in entries_}),
            }
        )
    rows.sort(key=lambda r: str(r["user"]).lower())
    return rows


def _h(minutes: int) -> Decimal:
    return (Decimal(minutes) / 60).quantize(Decimal("0.01"))


@transaction.atomic
def copy_week(week_start: date, user) -> int:
    """Copy last week's schedule into this week (days that already have shifts are left alone)."""
    prev = week_start - timedelta(days=7)
    existing = set(
        ScheduledShift.objects.filter(date__range=(week_start, week_start + timedelta(days=6))).values_list("user_id", "date")
    )
    n = 0
    for s in ScheduledShift.objects.filter(date__range=(prev, prev + timedelta(days=6))):
        new_date = s.date + timedelta(days=7)
        if (s.user_id, new_date) in existing:
            continue
        ScheduledShift.objects.create(user=s.user, date=new_date, start=s.start, end=s.end, position=s.position, note=s.note)
        n += 1
    audit(user, "staff.copy_week", f"{week_start}: {n}")
    return n
