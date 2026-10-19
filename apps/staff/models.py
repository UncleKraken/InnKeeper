"""
People who work here: their employment details (for management only), when they clock in and
out, and the weekly schedule. The till's cash shifts (finance.Shift) are separate: those count money.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

MONEY = {"max_digits": 12, "decimal_places": 2}


class Position(models.Model):
    COLORS = [
        ("teal", _("Teal")),
        ("blue", _("Blue")),
        ("amber", _("Amber")),
        ("rose", _("Rose")),
        ("violet", _("Violet")),
        ("slate", _("Grey")),
    ]
    name = models.CharField(_("name"), max_length=60, unique=True)
    color = models.CharField(_("colour"), max_length=10, choices=COLORS, default="teal")
    sort_order = models.PositiveSmallIntegerField(_("order"), default=0)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("position")
        verbose_name_plural = _("positions")
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class EmployeeProfile(models.Model):
    """Employment details. Personal data: only managers see and change it."""

    class Kind(models.TextChoices):
        FULL_TIME = "full_time", _("Full time")
        PART_TIME = "part_time", _("Part time")
        SEASONAL = "seasonal", _("Seasonal")
        TRAINEE = "trainee", _("Trainee / intern")
        EXTERNAL = "external", _("External / agency")

    class Pay(models.TextChoices):
        NONE = "", _("Not recorded")
        MONTHLY = "monthly", _("Monthly salary (gross)")
        HOURLY = "hourly", _("Hourly rate (gross)")

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="employee")
    position = models.ForeignKey(
        Position, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees", verbose_name=_("position")
    )
    employment = models.CharField(_("employment"), max_length=12, choices=Kind.choices, default=Kind.FULL_TIME)
    start_date = models.DateField(_("started on"), null=True, blank=True)
    end_date = models.DateField(_("left on"), null=True, blank=True)
    weekly_hours = models.DecimalField(
        _("contract hours per week"), null=True, blank=True, max_digits=5, decimal_places=1,
        validators=[MinValueValidator(Decimal("0"))],
    )
    date_of_birth = models.DateField(_("date of birth"), null=True, blank=True)
    personal_id = models.CharField(_("personal ID number (NID)"), max_length=30, blank=True)
    address = models.CharField(_("address"), max_length=200, blank=True)
    emergency_contact = models.CharField(
        _("emergency contact"), max_length=120, blank=True, help_text=_("Name and phone number.")
    )
    pay_type = models.CharField(_("pay"), max_length=10, choices=Pay.choices, blank=True, default="")
    pay_rate = models.DecimalField(_("amount"), null=True, blank=True, validators=[MinValueValidator(Decimal("0"))], **MONEY)
    bank_account = models.CharField(_("bank account (IBAN)"), max_length=40, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("employee details")
        verbose_name_plural = _("employee details")

    def __str__(self) -> str:
        return str(self.user)


class TimeEntry(models.Model):
    """One stretch of work: clocked in → clocked out."""

    class Source(models.TextChoices):
        PIN = "pin", _("PIN pad")
        WEB = "web", _("InnKeeper")
        MANUAL = "manual", _("Added by a manager")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="time_entries")
    position = models.ForeignKey(Position, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    clock_in = models.DateTimeField(_("clock in"))
    clock_out = models.DateTimeField(_("clock out"), null=True, blank=True)
    break_minutes = models.PositiveSmallIntegerField(_("break (minutes)"), default=0)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.WEB)
    note = models.CharField(_("note"), max_length=200, blank=True)
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    edit_reason = models.CharField(_("reason for the change"), max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("time entry")
        verbose_name_plural = _("time entries")
        ordering = ["-clock_in"]
        constraints = [
            models.UniqueConstraint(fields=["user"], condition=models.Q(clock_out__isnull=True), name="one_open_time_entry")
        ]

    def __str__(self) -> str:
        return f"{self.user} {self.clock_in:%Y-%m-%d %H:%M}"

    @property
    def is_open(self) -> bool:
        return self.clock_out is None

    @property
    def minutes(self) -> int:
        end = self.clock_out or timezone.now()
        return max(0, int((end - self.clock_in).total_seconds() // 60) - self.break_minutes)

    @property
    def hours(self) -> Decimal:
        return (Decimal(self.minutes) / 60).quantize(Decimal("0.01"))

    @property
    def forgotten(self) -> bool:
        """Still clocked in after 16 hours: almost certainly a missing clock-out."""
        return self.clock_out is None and timezone.now() - self.clock_in > timedelta(hours=16)


class ScheduledShift(models.Model):
    """A planned shift on the weekly schedule. An end before the start means it ends the next day."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scheduled_shifts")
    date = models.DateField(_("date"), db_index=True)
    start = models.TimeField(_("from"))
    end = models.TimeField(_("to"))
    position = models.ForeignKey(Position, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name=_("position"))
    note = models.CharField(_("note"), max_length=120, blank=True)

    class Meta:
        verbose_name = _("scheduled shift")
        verbose_name_plural = _("schedule")
        ordering = ["date", "start"]

    def __str__(self) -> str:
        return f"{self.user} {self.date} {self.start:%H:%M}–{self.end:%H:%M}"

    @property
    def starts_at(self) -> datetime:
        return timezone.make_aware(datetime.combine(self.date, self.start))

    @property
    def ends_at(self) -> datetime:
        end = datetime.combine(self.date, self.end)
        if self.end <= self.start:
            end += timedelta(days=1)
        return timezone.make_aware(end)

    @property
    def minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)

    @property
    def hours(self) -> Decimal:
        return (Decimal(self.minutes) / 60).quantize(Decimal("0.01"))
