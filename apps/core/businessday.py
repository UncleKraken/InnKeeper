"""
The business day.

A bar that closes at 03:00 still thinks of 01:30 as "Saturday night". With *Business day ends at*
set to 04:00, everything until 04:00 belongs to the day before: sales, payments, expenses, stock
and the day close. Room nights, housekeeping, fiscal receipts and receipt numbering stay on the
calendar date, as the law and the guests expect.
"""

from datetime import date, datetime, time, timedelta

from django.utils import timezone


def _cutoff() -> int:
    from apps.core.models import HotelSettings

    return int(HotelSettings.load().day_ends_at or 0)


def business_date(when: datetime | None = None) -> date:
    """The business day a moment belongs to (now by default)."""
    local = timezone.localtime(when or timezone.now())
    if local.hour < _cutoff():
        return local.date() - timedelta(days=1)
    return local.date()


def day_start(day: date) -> datetime:
    """When a business day begins, as an aware datetime."""
    return timezone.make_aware(datetime.combine(day, time(hour=_cutoff())))


def day_range(start: date, end: date | None = None) -> tuple[datetime, datetime]:
    """[from, to) covering the business days start…end, for filtering timestamps such as closed_at."""
    return day_start(start), day_start((end or start) + timedelta(days=1))
