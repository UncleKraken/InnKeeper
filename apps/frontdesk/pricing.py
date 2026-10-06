"""
Nightly prices from the price list.

For each night of a stay:
1. A season with a *fixed price* for that room type wins (the most recently started one if several overlap).
2. Otherwise every season with a *percentage* that covers the night is applied to the base rate
   (the most recently started one if several overlap).
3. Otherwise the room type's base rate.

A stay must also be at least as long as the longest `min_nights` of the seasons it touches.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .models import RoomType, SeasonRate

CENT = Decimal("0.01")


@dataclass
class Quote:
    room_type: RoomType
    arrival: date
    departure: date
    nightly: list[Decimal] = field(default_factory=list)
    min_nights: int = 1

    @property
    def nights(self) -> int:
        return (self.departure - self.arrival).days

    @property
    def total(self) -> Decimal:
        return sum(self.nightly, Decimal("0.00"))

    @property
    def average(self) -> Decimal:
        return (self.total / self.nights).quantize(CENT, ROUND_HALF_UP) if self.nights else Decimal("0.00")

    @property
    def meets_min_nights(self) -> bool:
        return self.nights >= self.min_nights

    @property
    def varies(self) -> bool:
        return len(set(self.nightly)) > 1

    def as_json(self) -> list[str]:
        return [str(x) for x in self.nightly] if self.varies else []


def quote(room_type: RoomType, arrival: date, departure: date) -> Quote:
    seasons = list(
        SeasonRate.objects.filter(is_active=True, start_date__lt=departure, end_date__gte=arrival)
        .filter(room_type__in=[room_type])
        .order_by("-start_date", "-id")
    ) + list(
        SeasonRate.objects.filter(
            is_active=True, start_date__lt=departure, end_date__gte=arrival, room_type__isnull=True
        ).order_by("-start_date", "-id")
    )
    q = Quote(room_type, arrival, departure)
    day = arrival
    while day < departure:
        covering = [s for s in seasons if s.start_date <= day <= s.end_date]
        fixed = next((s for s in covering if s.rate is not None and s.room_type_id == room_type.pk), None)
        pct = next((s for s in covering if s.percent is not None), None)
        if fixed is not None:
            price = fixed.rate
        elif pct is not None:
            price = room_type.base_rate * (Decimal("100") + pct.percent) / Decimal("100")
        else:
            price = room_type.base_rate
        q.nightly.append(max(Decimal("0"), price).quantize(CENT, ROUND_HALF_UP))
        q.min_nights = max([q.min_nights] + [s.min_nights for s in covering])
        day += timedelta(days=1)
    return q


def apply_quote(reservation, q: Quote) -> None:
    """Set a reservation's price from a quote."""
    reservation.rate = q.average if q.varies else (q.nightly[0] if q.nightly else q.room_type.base_rate)
    reservation.nightly_rates = q.as_json()
