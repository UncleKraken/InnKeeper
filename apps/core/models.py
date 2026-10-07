import threading
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

_request_local = threading.local()


def clear_settings_cache() -> None:
    _request_local.hotel_settings = None


class HotelSettings(models.Model):
    """Single row holding the property's details. Use `HotelSettings.load()`."""

    name = models.CharField(_("hotel name"), max_length=120, default="InnKeeper Hotel")
    legal_name = models.CharField(_("legal name"), max_length=160, blank=True)
    tax_id = models.CharField(_("tax ID (NIPT)"), max_length=40, blank=True)
    address = models.CharField(_("address"), max_length=255, blank=True)
    phone = models.CharField(_("phone"), max_length=40, blank=True)
    email = models.EmailField(_("email"), blank=True)
    currency = models.CharField(_("currency code"), max_length=3, default="EUR")
    currency_symbol = models.CharField(_("currency symbol"), max_length=5, default="€")
    check_in_time = models.TimeField(_("standard check-in time"), default="14:00")
    check_out_time = models.TimeField(_("standard check-out time"), default="11:00")
    vat_rate = models.DecimalField(
        _("VAT rate (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("20.00"),
        help_text=_("Prices are entered including VAT. Used to show the VAT portion on invoices."),
    )
    invoice_footer = models.TextField(_("invoice footer"), blank=True)

    class BusinessType(models.TextChoices):
        HOTEL = "hotel", _("Hotel with restaurant, bar and services")
        GUESTHOUSE = "guesthouse", _("Guesthouse, B&B, hostel or apartments")
        RESTAURANT = "restaurant", _("Restaurant, bar or café (no rooms)")

    business_type = models.CharField(
        _("type of business"), max_length=20, choices=BusinessType.choices, default=BusinessType.HOTEL
    )
    module_rooms = models.BooleanField(
        _("rooms & front desk"), default=True, help_text=_("Reservations, room rack, guests and guest bills.")
    )
    module_housekeeping = models.BooleanField(_("housekeeping"), default=True)
    module_maintenance = models.BooleanField(_("maintenance"), default=True)
    module_outlets = models.BooleanField(
        _("restaurant, bar & services"),
        default=True,
        help_text=_("Point of sale for restaurant, bar, spa and other services."),
    )
    module_inventory = models.BooleanField(
        _("stock & inventory"),
        default=True,
        help_text=_("Ingredients and products, recipes, deliveries and stock counts."),
    )
    setup_completed = models.BooleanField(default=False)
    onboarding_dismissed = models.BooleanField(default=False)
    default_language = models.CharField(
        _("default language"), max_length=8, choices=[("sq", _("Albanian")), ("en", _("English"))], default="sq"
    )

    # Receipts and invoices
    logo = models.TextField(_("logo"), blank=True, help_text=_("Stored inside the database so it moves with backups."))
    receipt_header = models.TextField(
        _("receipt header"),
        blank=True,
        help_text=_("Extra lines under the name, e.g. opening hours or Wi-Fi password."),
    )
    receipt_footer = models.TextField(_("receipt footer"), blank=True, default="Faleminderit! · Thank you!")
    receipt_width = models.PositiveSmallIntegerField(
        _("receipt paper width"), choices=[(58, "58 mm"), (80, "80 mm")], default=80
    )
    receipt_show_logo = models.BooleanField(_("show logo on receipts"), default=True)
    receipt_show_vat = models.BooleanField(_("show VAT breakdown on receipts"), default=True)
    max_staff_discount = models.PositiveSmallIntegerField(
        _("maximum discount for service staff (%)"),
        default=0,
        help_text=_("0 means only managers can give discounts."),
    )
    # Online booking page
    booking_enabled = models.BooleanField(
        _("accept online bookings"), default=False, help_text=_("Opens the public booking page for your website.")
    )
    booking_requires_confirmation = models.BooleanField(
        _("confirm each online booking by hand"),
        default=True,
        help_text=_("Bookings arrive as requests; reception confirms them. Turn off to confirm instantly."),
    )
    booking_deposit_percent = models.PositiveSmallIntegerField(
        _("deposit (%)"),
        default=0,
        help_text=_("Share of the stay to pay in advance by bank transfer. 0 = pay at the hotel."),
    )
    booking_min_days_ahead = models.PositiveSmallIntegerField(
        _("book at least (days ahead)"), default=0, help_text=_("0 allows same-day bookings.")
    )
    booking_max_days_ahead = models.PositiveSmallIntegerField(_("book at most (days ahead)"), default=365)
    booking_intro = models.TextField(_("welcome text"), blank=True)
    booking_terms = models.TextField(
        _("booking conditions"), blank=True, help_text=_("Cancellation policy, check-in times, house rules…")
    )
    bank_details = models.TextField(
        _("bank details for deposits"), blank=True, help_text=_("Bank name, IBAN and account holder.")
    )
    public_url = models.URLField(
        _("public web address of InnKeeper"),
        blank=True,
        help_text=_("e.g. https://book.yourhotel.al — used for links in emails and the QR menu."),
    )
    notify_email = models.EmailField(
        _("send new booking alerts to"), blank=True, help_text=_("Usually the reception email address.")
    )

    # Outgoing email (SMTP)
    smtp_host = models.CharField(_("SMTP server"), max_length=120, blank=True, help_text=_("e.g. smtp.gmail.com"))
    smtp_port = models.PositiveIntegerField(_("port"), default=587)
    smtp_username = models.CharField(_("username"), max_length=120, blank=True)
    smtp_password = models.CharField(
        _("password"),
        max_length=200,
        blank=True,
        help_text=_("For Gmail, use an app password, not your normal password."),
    )
    smtp_security = models.CharField(
        _("security"),
        max_length=8,
        choices=[("tls", "STARTTLS (587)"), ("ssl", "SSL/TLS (465)"), ("none", _("None"))],
        default="tls",
    )
    email_from = models.EmailField(_("send emails from"), blank=True)

    # Online card payments
    payment_provider = models.CharField(
        _("payment provider"),
        max_length=12,
        choices=[("", _("None")), ("pok", "POK"), ("paysera", "Paysera")],
        blank=True,
    )
    payment_test_mode = models.BooleanField(
        _("test mode"), default=True, help_text=_("Use the provider's test system. No real money is charged.")
    )
    pok_key_id = models.CharField(_("POK key ID"), max_length=120, blank=True)
    pok_key_secret = models.CharField(_("POK key secret"), max_length=255, blank=True)
    pok_merchant_id = models.CharField(_("POK merchant ID"), max_length=120, blank=True)
    paysera_project_id = models.CharField(_("Paysera project ID"), max_length=20, blank=True)
    paysera_password = models.CharField(_("Paysera project password"), max_length=120, blank=True)
    booking_card_deposit = models.BooleanField(
        _("let guests pay the deposit by card"),
        default=True,
        help_text=_("Shows a “Pay now” button on the online booking page when a payment provider is set up."),
    )

    # Channel manager (Channex)
    channex_enabled = models.BooleanField(_("connect to the channel manager"), default=False)
    channex_api_key = models.CharField(_("Channex API key"), max_length=255, blank=True)
    channex_property_id = models.CharField(_("Channex property ID"), max_length=64, blank=True)
    channex_staging = models.BooleanField(
        _("use the Channex test system (staging)"), default=False, help_text=_("For trying it out before going live.")
    )
    channex_days_ahead = models.PositiveSmallIntegerField(_("send availability for (days)"), default=365)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("hotel settings")
        verbose_name_plural = _("hotel settings")

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        clear_settings_cache()

    def delete(self, *args, **kwargs):  # the settings row is never deleted
        return

    @classmethod
    def load(cls) -> "HotelSettings":
        """The settings row, loaded at most once per request (see SettingsCacheMiddleware)."""
        obj = getattr(_request_local, "hotel_settings", None)
        if obj is None:
            obj, _created = cls.objects.get_or_create(pk=1)
            _request_local.hotel_settings = obj
        return obj

    @property
    def vat_fraction(self) -> Decimal:
        """Share of a VAT-inclusive price that is VAT, e.g. 20% → 1/6."""
        return self.vat_rate / (Decimal("100") + self.vat_rate) if self.vat_rate else Decimal("0")

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and (self.email_from or self.smtp_username))

    @property
    def payments_configured(self) -> bool:
        if self.payment_provider == "pok":
            return bool(self.pok_key_id and self.pok_key_secret and self.pok_merchant_id)
        if self.payment_provider == "paysera":
            return bool(self.paysera_project_id and self.paysera_password)
        return False

    @property
    def channex_configured(self) -> bool:
        return bool(self.channex_enabled and self.channex_api_key and self.channex_property_id and self.module_rooms)

    @property
    def booking_open(self) -> bool:
        return self.booking_enabled and self.module_rooms

    def enabled_modules(self) -> set[str]:
        mods = {"finance", "management"}
        if self.module_rooms:
            mods |= {"frontdesk", "guests"}
        if self.module_housekeeping and self.module_rooms:
            mods.add("housekeeping")
        if self.module_maintenance:
            mods.add("maintenance")
        if self.module_outlets:
            mods |= {"outlets", "kitchen"}
        if self.module_inventory:
            mods.add("inventory")
        return mods


class Sequence(models.Model):
    """Gap-free counters for receipt and invoice numbers (one row per series and year)."""

    key = models.CharField(max_length=40, unique=True)
    value = models.PositiveIntegerField(default=0)

    @classmethod
    def next(cls, series: str, year: int) -> str:
        from django.db import transaction

        with transaction.atomic():
            row, _created = cls.objects.select_for_update().get_or_create(key=f"{series}-{year}")
            row.value += 1
            row.save(update_fields=["value"])
        return f"{year}-{row.value:06d}"


class AuditLog(models.Model):
    """Who did what, and when. Written for every action that touches money or stays."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    action = models.CharField(_("action"), max_length=60)
    description = models.CharField(_("description"), max_length=255)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(_("time"), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("audit entry")
        verbose_name_plural = _("audit log")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}: {self.description}"


def audit(user, action: str, description: str, obj=None) -> AuditLog:
    return AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        description=str(description)[:255],
        object_type=obj._meta.label if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
    )
