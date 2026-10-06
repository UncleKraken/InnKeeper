from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

MONEY = {"max_digits": 12, "decimal_places": 2}


class RoomType(models.Model):
    name = models.CharField(_("name"), max_length=80)
    code = models.CharField(_("code"), max_length=12, unique=True, help_text=_("Short code, e.g. DBL, TWN, STE."))
    description = models.TextField(_("description"), blank=True)
    base_rate = models.DecimalField(_("nightly rate"), validators=[MinValueValidator(0)], **MONEY)
    max_adults = models.PositiveSmallIntegerField(_("max adults"), default=2)
    max_children = models.PositiveSmallIntegerField(_("max children"), default=1)
    is_active = models.BooleanField(_("active"), default=True)
    # Online booking page
    bookable_online = models.BooleanField(
        _("bookable online"), default=True, help_text=_("Show this room type on the public booking page.")
    )
    name_en = models.CharField(_("name in English"), max_length=80, blank=True)
    description_en = models.TextField(_("description in English"), blank=True)
    photo = models.TextField(_("photo"), blank=True)
    sort_order = models.PositiveSmallIntegerField(_("order"), default=0)

    class Meta:
        verbose_name = _("room type")
        verbose_name_plural = _("room types")
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Room(models.Model):
    class HKStatus(models.TextChoices):
        CLEAN = "clean", _("Clean")
        DIRTY = "dirty", _("Dirty")
        INSPECTED = "inspected", _("Inspected")

    number = models.CharField(_("room number"), max_length=10, unique=True)
    room_type = models.ForeignKey(RoomType, on_delete=models.PROTECT, related_name="rooms", verbose_name=_("room type"))
    floor = models.SmallIntegerField(_("floor"), default=1)
    hk_status = models.CharField(
        _("housekeeping status"), max_length=12, choices=HKStatus.choices, default=HKStatus.CLEAN
    )
    out_of_order = models.BooleanField(_("out of order"), default=False)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("room")
        verbose_name_plural = _("rooms")
        ordering = ["floor", "number"]

    def __str__(self) -> str:
        return self.number

    @property
    def is_ready(self) -> bool:
        return not self.out_of_order and self.hk_status in (self.HKStatus.CLEAN, self.HKStatus.INSPECTED)

    def current_reservation(self):
        return self.reservations.filter(status=Reservation.Status.CHECKED_IN).select_related("guest").first()


class Guest(models.Model):
    class DocumentType(models.TextChoices):
        ID_CARD = "id_card", _("ID card")
        PASSPORT = "passport", _("Passport")
        DRIVING_LICENCE = "driving_licence", _("Driving licence")
        OTHER = "other", _("Other")

    first_name = models.CharField(_("first name"), max_length=80)
    last_name = models.CharField(_("last name"), max_length=80)
    email = models.EmailField(_("email"), blank=True)
    phone = models.CharField(_("phone"), max_length=40, blank=True)
    nationality = models.CharField(_("nationality"), max_length=60, blank=True)
    document_type = models.CharField(_("document type"), max_length=20, choices=DocumentType.choices, blank=True)
    document_number = models.CharField(_("document number"), max_length=60, blank=True)
    date_of_birth = models.DateField(_("date of birth"), null=True, blank=True)
    address = models.CharField(_("address"), max_length=255, blank=True)
    company = models.CharField(_("company"), max_length=120, blank=True)
    is_vip = models.BooleanField(_("VIP"), default=False)
    notes = models.TextField(_("notes"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("guest")
        verbose_name_plural = _("guests")
        ordering = ["last_name", "first_name"]
        indexes = [models.Index(fields=["last_name", "first_name"])]

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Reservation(models.Model):
    class Status(models.TextChoices):
        BOOKED = "booked", _("Booked")
        CHECKED_IN = "checked_in", _("In house")
        CHECKED_OUT = "checked_out", _("Checked out")
        CANCELLED = "cancelled", _("Cancelled")
        NO_SHOW = "no_show", _("No-show")

    class Source(models.TextChoices):
        WALK_IN = "walk_in", _("Walk-in")
        PHONE = "phone", _("Phone")
        EMAIL = "email", _("Email")
        WEBSITE = "website", _("Website")
        BOOKING_COM = "booking_com", _("Booking.com")
        AIRBNB = "airbnb", _("Airbnb")
        EXPEDIA = "expedia", _("Expedia")
        AGENCY = "agency", _("Travel agency")
        OTHER = "other", _("Other")

    ACTIVE_STATUSES = (Status.BOOKED, Status.CHECKED_IN)

    guest = models.ForeignKey(Guest, on_delete=models.PROTECT, related_name="reservations", verbose_name=_("guest"))
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="reservations", verbose_name=_("room"))
    arrival = models.DateField(_("arrival"))
    departure = models.DateField(_("departure"))
    adults = models.PositiveSmallIntegerField(_("adults"), default=1, validators=[MinValueValidator(1)])
    children = models.PositiveSmallIntegerField(_("children"), default=0)
    rate = models.DecimalField(_("nightly rate"), validators=[MinValueValidator(0)], **MONEY)
    # One price per night when seasons apply (as strings, e.g. ["80.00", "80.00", "104.00"]); empty = `rate` every night.
    nightly_rates = models.JSONField(default=list, blank=True)
    status = models.CharField(_("status"), max_length=12, choices=Status.choices, default=Status.BOOKED, db_index=True)
    source = models.CharField(_("source"), max_length=20, choices=Source.choices, default=Source.WALK_IN)
    external_ref = models.CharField(_("external reference"), max_length=60, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    # Online bookings
    confirmed = models.BooleanField(_("confirmed"), default=True)
    booking_token = models.CharField(max_length=32, blank=True, db_index=True)
    guest_language = models.CharField(max_length=8, blank=True)
    deposit_due = models.DecimalField(_("deposit due"), default=Decimal("0.00"), **MONEY)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("reservation")
        verbose_name_plural = _("reservations")
        ordering = ["-arrival", "-id"]
        indexes = [models.Index(fields=["room", "arrival", "departure"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(departure__gt=models.F("arrival")), name="reservation_departure_after_arrival"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} – {self.guest}"

    @property
    def code(self) -> str:
        return f"R{self.pk:06d}" if self.pk else "—"

    @property
    def nights(self) -> int:
        return (self.departure - self.arrival).days

    def rate_for_night(self, index: int) -> Decimal:
        """Price of the night starting `index` days after arrival."""
        if self.nightly_rates and len(self.nightly_rates) == self.nights and 0 <= index < self.nights:
            return Decimal(str(self.nightly_rates[index]))
        return self.rate

    def amount_for_nights(self, start: int, end: int) -> Decimal:
        return sum((self.rate_for_night(i) for i in range(start, end)), Decimal("0.00"))

    @property
    def has_varying_rates(self) -> bool:
        return bool(self.nightly_rates) and len(set(map(str, self.nightly_rates))) > 1

    @property
    def nightly_breakdown(self) -> list[tuple[date, Decimal]]:
        return [(self.arrival + timedelta(days=i), self.rate_for_night(i)) for i in range(self.nights)]

    @property
    def estimated_total(self) -> Decimal:
        return self.amount_for_nights(0, self.nights)

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    def overlapping(self):
        """Other active reservations for the same room whose dates overlap this one."""
        qs = Reservation.objects.filter(
            room_id=self.room_id,
            status__in=self.ACTIVE_STATUSES,
            arrival__lt=self.departure,
            departure__gt=self.arrival,
        )
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        return qs

    def clean(self):
        errors = {}
        if self.arrival and self.departure and self.departure <= self.arrival:
            errors["departure"] = _("Departure must be after arrival.")
        if self.room_id and self.arrival and self.departure and not errors and self.is_active:
            clash = self.overlapping().select_related("guest").first()
            if clash:
                errors["room"] = _("Room %(room)s is already booked from %(start)s to %(end)s (%(guest)s).") % {
                    "room": self.room.number,
                    "start": clash.arrival.strftime("%d.%m.%Y"),
                    "end": clash.departure.strftime("%d.%m.%Y"),
                    "guest": clash.guest,
                }
        if self.room_id and self.adults is not None:
            rt = self.room.room_type
            if self.adults > rt.max_adults or (self.children or 0) > rt.max_children:
                errors["adults"] = _("This room type allows at most %(a)s adults and %(c)s children.") % {
                    "a": rt.max_adults,
                    "c": rt.max_children,
                }
        if errors:
            raise ValidationError(errors)

    def nights_to_charge(self, on_date: date | None = None) -> int:
        """Nights actually stayed if the guest leaves on `on_date` (at least one)."""
        on_date = on_date or timezone.localdate()
        return max(1, (on_date - self.arrival).days)


class SeasonRate(models.Model):
    """A price change for a period: a fixed nightly price for one room type, or a percentage for all."""

    name = models.CharField(_("name"), max_length=80, help_text=_("e.g. Summer, New Year, Low season"))
    room_type = models.ForeignKey(
        RoomType,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="season_rates",
        verbose_name=_("room type"),
        help_text=_("Leave empty to apply to all room types (percentage only)."),
    )
    start_date = models.DateField(_("from"))
    end_date = models.DateField(_("until (including)"))
    rate = models.DecimalField(_("nightly price"), null=True, blank=True, validators=[MinValueValidator(0)], **MONEY)
    percent = models.DecimalField(
        _("change (%)"),
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("e.g. 30 for +30%, -15 for a 15% discount."),
    )
    min_nights = models.PositiveSmallIntegerField(_("minimum nights"), default=1)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("season")
        verbose_name_plural = _("seasons")
        ordering = ["start_date", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.start_date:%d.%m}–{self.end_date:%d.%m.%Y})"

    def clean(self):
        errors = {}
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors["end_date"] = _("The end date must be on or after the start date.")
        if (self.rate is None) == (self.percent is None):
            errors["rate"] = _("Enter either a nightly price or a percentage change, not both.")
        elif self.rate is not None and not self.room_type_id:
            errors["room_type"] = _("A fixed price needs a room type.")
        if errors:
            raise ValidationError(errors)
