"""
Monthly payroll from the clock-ins: gross pay for each person, with the extras for overtime, night
work and public holidays.

* Hourly pay: hours worked × rate.
* Monthly salary: the salary (for the days employed that month); the extras use the salary's hourly
  value, salary ÷ (contract hours a week × 52 ÷ 12).
* Overtime: in each week (Monday–Sunday), the hours beyond the person's contract hours (40 if not set).
* Night: hours between 22:00 and 06:00. Public holiday: hours on a day in the holiday list.
* Bonuses and advances: one-off amounts for the month.

This is gross pay. Contributions and income tax are left to the accountant: their caps and brackets
change by decision every year, and a wrong figure on a payslip is worse than none.
"""

import calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import HotelSettings

from .models import EmployeeProfile, PayAdjustment, PublicHoliday, TimeEntry

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
NIGHT_START, NIGHT_END = 22, 6
WEEKS_PER_MONTH = Decimal(52) / Decimal(12)


def money(v) -> Decimal:
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def hours(minutes) -> Decimal:
    return (Decimal(minutes) / 60).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------- Public holidays ----------


def western_easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def orthodox_easter(year: int) -> date:
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = (d + e + 114) % 31 + 1
    return date(year, month, day) + timedelta(days=13)  # Julian → Gregorian (1900–2099)


def albanian_holidays(year: int) -> list[tuple[date, str]]:
    """The holidays with a known date. Bajram days are set each year by the government, so they are added by hand."""
    return [
        (date(year, 1, 1), _("New Year")),
        (date(year, 1, 2), _("New Year")),
        (date(year, 3, 14), _("Summer Day")),
        (date(year, 3, 22), _("Nevruz")),
        (western_easter(year), _("Catholic Easter")),
        (orthodox_easter(year), _("Orthodox Easter")),
        (date(year, 5, 1), _("Workers' Day")),
        (date(year, 9, 5), _("Mother Teresa Day")),
        (date(year, 11, 28), _("Independence Day")),
        (date(year, 11, 29), _("Liberation Day")),
        (date(year, 12, 8), _("Youth Day")),
        (date(year, 12, 25), _("Christmas")),
    ]


def add_albanian_holidays(year: int) -> int:
    n = 0
    for d, name in albanian_holidays(year):
        _obj, created = PublicHoliday.objects.get_or_create(date=d, defaults={"name": name})
        n += created
    return n


# ---------- Splitting worked time ----------


def _split(entry: TimeEntry, holidays: set[date]) -> tuple[int, int]:
    """Night minutes and holiday minutes of an entry (breaks taken out in proportion)."""
    start, end = timezone.localtime(entry.clock_in), timezone.localtime(entry.clock_out)
    span = int((end - start).total_seconds() // 60)
    if span <= 0:
        return 0, 0
    night = holiday = 0
    t = start
    while t < end:
        day_start = datetime.combine(t.date(), time.min, tzinfo=t.tzinfo)
        boundaries = [day_start + timedelta(hours=h) for h in (NIGHT_END, NIGHT_START, 24)]
        nxt = min([b for b in boundaries if b > t] + [end])
        minutes = (nxt - t).total_seconds() / 60
        if t.hour >= NIGHT_START or t.hour < NIGHT_END:
            night += minutes
        if t.date() in holidays:
            holiday += minutes
        t = nxt
    worked = entry.minutes
    return round(night * worked / span), round(holiday * worked / span)


def _overtime(entries: list[TimeEntry], weekly_limit_minutes: int) -> dict[int, int]:
    """Overtime minutes per entry: in each week, what comes after the contract hours are reached."""
    by_week: dict[tuple, list] = defaultdict(list)
    for e in entries:
        by_week[timezone.localtime(e.clock_in).isocalendar()[:2]].append(e)
    out = {}
    for week in by_week.values():
        total = 0
        for e in sorted(week, key=lambda x: x.clock_in):
            before = total
            total += e.minutes
            out[e.pk] = max(0, total - max(before, weekly_limit_minutes))
    return out


# ---------- The month ----------


def month_bounds(month: date) -> tuple[date, date]:
    """The pay period named after `month`: the calendar month, or (when it starts on another day) from that
    day of the month before to the day before it in this month."""
    first = month.replace(day=1)
    start_day = HotelSettings.load().payroll_period_start or 1
    if start_day <= 1:
        return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])
    prev = (first - timedelta(days=1)).replace(day=1)
    return prev.replace(day=start_day), first.replace(day=start_day - 1)


def calculate(month: date, users=None) -> list[dict]:
    hs = HotelSettings.load()
    first, last = month_bounds(month)
    # Whole weeks around the month, so overtime in a week that crosses the month is counted right.
    week_from = first - timedelta(days=first.weekday())
    week_to = last + timedelta(days=6 - last.weekday())
    since = timezone.make_aware(datetime.combine(week_from, time.min))
    until = timezone.make_aware(datetime.combine(week_to + timedelta(days=1), time.min))
    entries = TimeEntry.objects.filter(clock_in__gte=since, clock_in__lt=until, clock_out__isnull=False).select_related("user")
    if users is not None:
        entries = entries.filter(user__in=users)
    holidays = (
        set(PublicHoliday.objects.filter(date__range=(week_from, week_to), paid=True).values_list("date", flat=True))
        if hs.payroll_holiday_pay
        else set()
    )
    by_user = defaultdict(list)
    for e in entries:
        by_user[e.user].append(e)
    profiles = {p.user_id: p for p in EmployeeProfile.objects.select_related("user", "position")}
    people = set(by_user)
    for p in profiles.values():
        if p.pay_type == EmployeeProfile.Pay.MONTHLY and p.user.is_active and _employed_days(p, first, last):
            people.add(p.user)
    adjustments = defaultdict(list)
    for a in PayAdjustment.objects.filter(month=first).select_related("user"):
        adjustments[a.user].append(a)
        people.add(a.user)
    if users is not None:
        people = {u for u in people if u in set(users)}

    rows = []
    for user in sorted(people, key=lambda u: str(u).lower()):
        p = profiles.get(user.pk)
        weekly = Decimal(p.weekly_hours) if p and p.weekly_hours else Decimal(40)
        overtime = _overtime(by_user.get(user, []), int(weekly * 60))
        worked = night = holiday = ot = 0
        days = set()
        for e in by_user.get(user, []):
            d = timezone.localtime(e.clock_in).date()
            if not first <= d <= last:
                continue
            n, h = _split(e, holidays)
            worked += e.minutes
            night += n
            holiday += h
            ot += overtime.get(e.pk, 0)
            days.add(d)
        pay_type = p.pay_type if p else ""
        rate = Decimal(p.pay_rate) if p and p.pay_rate is not None else None
        base = hourly = None
        if pay_type == EmployeeProfile.Pay.HOURLY and rate is not None:
            hourly = rate
            base = money(hours(worked) * rate)
        elif pay_type == EmployeeProfile.Pay.MONTHLY and rate is not None:
            employed = _employed_days(p, first, last)
            month_days = (last - first).days + 1
            base = money(rate * employed / month_days) if employed < month_days else money(rate)
            hourly = (rate / (weekly * WEEKS_PER_MONTH)).quantize(Decimal("0.0001"))
        extras = {
            "overtime": money(hours(ot) * hourly * hs.payroll_overtime_percent / 100) if hourly else ZERO,
            "night": money(hours(night) * hourly * hs.payroll_night_percent / 100) if hourly else ZERO,
            "holiday": money(hours(holiday) * hourly * hs.payroll_holiday_percent / 100) if hourly else ZERO,
        }
        # Overtime for a monthly salary is also paid at the normal rate on top of the salary.
        if pay_type == EmployeeProfile.Pay.MONTHLY and hourly:
            extras["overtime"] += money(hours(ot) * hourly)
        adj = adjustments.get(user, [])
        adj_total = sum((a.amount for a in adj), ZERO)
        gross = None if base is None else money(base + sum(extras.values(), ZERO) + adj_total)
        rows.append(
            {
                "user": user,
                "user_id": user.pk,
                "name": user.get_full_name() or user.username,
                "position": str(p.position) if p and p.position else "",
                "pay_type": pay_type,
                "rate": rate,
                "hourly": hourly,
                "days": len(days),
                "hours": hours(worked),
                "overtime_hours": hours(ot),
                "night_hours": hours(night),
                "holiday_hours": hours(holiday),
                "base": base,
                "extras": extras,
                "adjustments": adj,
                "adjustments_total": adj_total,
                "gross": gross,
                "iban": p.bank_account if p else "",
                "missing_pay": base is None,
            }
        )
    return rows


def _employed_days(p: EmployeeProfile, first: date, last: date) -> int:
    start = max(first, p.start_date or first)
    end = min(last, p.end_date or last)
    return max(0, (end - start).days + 1)


def totals(rows: list[dict]) -> dict:
    return {
        "hours": sum((r["hours"] for r in rows), ZERO),
        "overtime_hours": sum((r["overtime_hours"] for r in rows), ZERO),
        "base": sum((r["base"] or ZERO for r in rows), ZERO),
        "extras": sum((sum(r["extras"].values(), ZERO) for r in rows), ZERO),
        "adjustments": sum((r["adjustments_total"] for r in rows), ZERO),
        "gross": sum((r["gross"] or ZERO for r in rows), ZERO),
    }


def frozen(rows: list[dict]) -> list[dict]:
    """The rows as stored when a month is approved (plain JSON)."""
    out = []
    for r in rows:
        out.append(
            {
                "user_id": r["user_id"], "name": r["name"], "position": r["position"], "pay_type": r["pay_type"],
                "rate": str(r["rate"]) if r["rate"] is not None else None, "days": r["days"],
                **{k: str(r[k]) for k in ("hours", "overtime_hours", "night_hours", "holiday_hours")},
                "base": str(r["base"]) if r["base"] is not None else None,
                "extras": {k: str(v) for k, v in r["extras"].items()},
                "adjustments": [{"amount": str(a.amount), "note": a.note} for a in r["adjustments"]],
                "adjustments_total": str(r["adjustments_total"]),
                "gross": str(r["gross"]) if r["gross"] is not None else None, "iban": r["iban"],
            }
        )
    return out


def thawed(rows: list[dict]) -> list[dict]:
    """Stored rows back into the shape the page uses."""
    out = []
    for r in rows:
        dec = lambda v: Decimal(v) if v is not None else None  # noqa: E731
        out.append(
            {
                **r,
                "rate": dec(r["rate"]),
                **{k: Decimal(r[k]) for k in ("hours", "overtime_hours", "night_hours", "holiday_hours", "adjustments_total")},
                "base": dec(r["base"]),
                "gross": dec(r["gross"]),
                "extras": {k: Decimal(v) for k, v in r["extras"].items()},
                "adjustments": [type("A", (), {"amount": Decimal(a["amount"]), "note": a["note"]}) for a in r["adjustments"]],
                "missing_pay": r["base"] is None,
            }
        )
    return out
