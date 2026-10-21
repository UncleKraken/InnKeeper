import threading
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

_request_local = threading.local()


def clear_settings_cache() -> None:
    _request_local.hotel_settings = None


class HotelSettings(models.Model):
    """Single row holding the property's details. Use `HotelSettings.load()`."""

    name = models.CharField(_("business name"), max_length=120, default="InnKeeper Hotel")
    legal_name = models.CharField(_("legal name"), max_length=160, blank=True)
    tax_id = models.CharField(_("tax ID (NIPT)"), max_length=40, blank=True)

    class TaxStatus(models.TextChoices):
        VAT = "vat", _("Registered, with VAT")
        NO_VAT = "no_vat", _("Registered, without VAT (small business)")
        NONE = "none", _("Not registered (association, outside Albania, internal use or trial)")

    tax_status = models.CharField(
        _("tax registration"),
        max_length=8,
        choices=TaxStatus.choices,
        default=TaxStatus.VAT,
        help_text=_(
            "Without VAT, receipts and invoices show no VAT. Not registered: no NIPT, VAT or fiscalization "
            "anywhere, and receipts say they are internal receipts. Ask your accountant if unsure."
        ),
    )
    address = models.CharField(_("address"), max_length=255, blank=True)
    phone = models.CharField(_("phone"), max_length=40, blank=True)
    email = models.EmailField(_("email"), blank=True)
    currency = models.CharField(_("currency code"), max_length=3, default="EUR")
    currency_symbol = models.CharField(_("currency symbol"), max_length=5, default="€")
    second_currency = models.CharField(
        _("second cash currency"), max_length=3, blank=True,
        help_text=_("Cash you also accept, e.g. EUR when your prices are in lekë (or ALL when they are in euros). Leave empty if you take only one."),
    )
    second_currency_symbol = models.CharField(_("its symbol"), max_length=5, blank=True)
    second_currency_rate = models.DecimalField(
        _("its rate"), max_digits=12, decimal_places=4, null=True, blank=True,
        help_text=_("How much 1 unit of the second currency is worth in your currency, e.g. 100 when 1 € = 100 lekë. Change it when your rate changes."),
    )
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
        NIGHTLIFE = "nightlife", _("Night bar, club or lounge (open after midnight)")

    business_type = models.CharField(
        _("type of business"), max_length=20, choices=BusinessType.choices, default=BusinessType.HOTEL
    )
    DAY_ENDS_CHOICES = [(0, _("Midnight (00:00)"))] + [(h, f"{h:02d}:00") for h in range(1, 9)]
    day_ends_at = models.PositiveSmallIntegerField(
        _("business day ends at"),
        default=0,
        choices=DAY_ENDS_CHOICES,
        help_text=_(
            "For places open after midnight: sales until this hour count on the previous day, so the "
            "night's takings are in one day close. Room nights and fiscal receipts keep the calendar date."
        ),
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

    # Owner's daily summary by email
    summary_to = models.CharField(
        _("send the daily summary to"),
        max_length=255,
        blank=True,
        help_text=_("One or more email addresses, separated by commas. Leave empty to send no summary."),
    )
    summary_hour = models.PositiveSmallIntegerField(
        _("send it at"),
        default=8,
        choices=[(h, f"{h:02d}:00") for h in range(24)],
        help_text=_("The summary of the day before is sent at this time. It is also sent right after the day close."),
    )
    summary_sent_for = models.DateField(null=True, blank=True, editable=False)
    demo_data = models.BooleanField(default=False, editable=False)  # filled with the sample business
    loyalty_enabled = models.BooleanField(
        _("loyalty cards"), default=False, help_text=_("Regulars collect a stamp for items marked “earns a loyalty stamp”.")
    )
    loyalty_stamps = models.PositiveSmallIntegerField(
        _("stamps for a free item"),
        default=9,
        validators=[MinValueValidator(2)],
        help_text=_("For example 9: after nine coffees the tenth is free."),
    )
    vouchers_enabled = models.BooleanField(_("gift vouchers"), default=False)
    voucher_months = models.PositiveSmallIntegerField(
        _("vouchers are valid for (months)"), default=12, help_text=_("0: they never expire.")
    )
    message_pre_arrival = models.BooleanField(
        _("email guests before they arrive"),
        default=False,
        help_text=_("Confirmed bookings with an email address get your arrival information a few days before."),
    )
    message_pre_arrival_days = models.PositiveSmallIntegerField(
        _("days before arrival"), default=2, validators=[MinValueValidator(1), MaxValueValidator(14)]
    )
    message_pre_arrival_text = models.TextField(
        _("arrival information"),
        blank=True,
        help_text=_("How to find you, parking, check-in, Wi-Fi… Write it in the language most of your guests read."),
    )
    message_review = models.BooleanField(
        _("ask for a review after check-out"),
        default=False,
        help_text=_("The day after they leave, guests with an email address get a thank-you with your review link."),
    )
    message_review_url = models.URLField(
        _("review link"),
        blank=True,
        help_text=_("Where guests leave a review: your Google Maps, TripAdvisor or Booking.com page."),
    )
    message_review_text = models.TextField(_("thank-you text"), blank=True)
    require_two_step = models.BooleanField(
        _("managers must use two-step sign-in"),
        default=False,
        help_text=_("Managers then need a 6-digit code from a phone app after their password. Strongly recommended when InnKeeper can be reached from the internet."),
    )
    online_checkin = models.BooleanField(
        _("let guests check in online"),
        default=True,
        help_text=_("The arrival email and the booking page carry a link where guests enter their ID or passport details, and those of the people with them, before they arrive. Needs the public web address."),
    )
    message_hour = models.PositiveSmallIntegerField(
        _("send at"), default=10, validators=[MaxValueValidator(23)], help_text=_("Hour of the day, 0–23.")
    )

    class TouristTaxBasis(models.TextChoices):
        GUEST = "guest", _("per guest, per night")
        ROOM = "room", _("per room, per night")

    tourist_tax_enabled = models.BooleanField(
        _("add the tourist tax to guest bills"),
        default=False,
        help_text=_("The tax your municipality charges on overnight stays. It is not your income and has no VAT."),
    )
    tourist_tax_amount = models.DecimalField(
        _("amount"),
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
        max_digits=12,
        decimal_places=2,
        help_text=_("In your currency, as the municipality sets it for your category (e.g. Tirana: 140 lek, 4–5 stars 350 lek)."),
    )
    tourist_tax_basis = models.CharField(
        _("charged"), max_length=8, choices=TouristTaxBasis.choices, default=TouristTaxBasis.GUEST
    )
    tourist_tax_children = models.BooleanField(
        _("children pay too"), default=False, help_text=_("Leave off if your municipality exempts children.")
    )
    tourist_tax_max_nights = models.PositiveSmallIntegerField(
        _("at most (nights per stay)"), default=0, help_text=_("0: every night is charged.")
    )
    breakfast_on = models.BooleanField(
        _("we serve breakfast"), default=False, help_text=_("Shows the morning breakfast list for the guests in house.")
    )
    breakfast_included_default = models.BooleanField(
        _("new bookings include breakfast"), default=True, help_text=_("Can be changed on each booking.")
    )
    breakfast_price = models.DecimalField(
        _("breakfast price per person"),
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
        max_digits=12,
        decimal_places=2,
        help_text=_("Added to the bill of guests whose booking doesn't include it."),
    )
    payroll_overtime_percent = models.PositiveSmallIntegerField(
        _("overtime extra (%)"), default=25, validators=[MaxValueValidator(300)],
        help_text=_("For hours over the contract hours in a week. The Labour Code asks for at least 25%."),
    )
    payroll_night_percent = models.PositiveSmallIntegerField(
        _("night work extra (%)"), default=20, validators=[MaxValueValidator(300)],
        help_text=_("For hours between 22:00 and 06:00, as your contracts or collective agreement say."),
    )
    payroll_holiday_pay = models.BooleanField(
        _("pay extra for public holidays"),
        default=False,
        help_text=_("Leave off if you're open every day (hotels, bars) and don't pay extra for public holidays. Choose the dates under Public holidays."),
    )
    payroll_period_start = models.PositiveSmallIntegerField(
        _("pay period starts on day"),
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
        help_text=_("1: calendar months. 26: the October pay runs from 26 September to 25 October."),
    )
    payroll_holiday_percent = models.PositiveSmallIntegerField(
        _("public holiday extra (%)"), default=25, validators=[MaxValueValidator(300)],
        help_text=_("For hours worked on a public holiday, as your contracts say."),
    )
    show_made_with = models.BooleanField(
        _("show “Made with InnKeeper” on public pages"),
        default=True,
        help_text=_("A small link at the bottom of your booking, menu and table pages. It helps other businesses find this free app."),
    )
    group_token = models.CharField(max_length=64, blank=True, editable=False)  # read-only key for the owner's group overview
    tunnel_enabled = models.BooleanField(_("public address through Cloudflare Tunnel"), default=False)
    tunnel_token = models.CharField(
        _("tunnel token"),
        max_length=600,
        blank=True,
        help_text=_("From Cloudflare Zero Trust → Networks → Tunnels → your tunnel → Install connector (the long text after --token)."),
    )
    pin_lock_minutes = models.PositiveSmallIntegerField(
        _("lock shared tills after"),
        default=3,
        choices=[(0, _("Never")), (1, _("1 minute")), (2, _("2 minutes")), (3, _("3 minutes")), (5, _("5 minutes")), (10, _("10 minutes"))],
        help_text=_("On a shared till, the screen goes back to the PIN pad after this long without a tap."),
    )

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

    # Fiscalization (direct to the tax authority, DPT)
    fiscal_enabled = models.BooleanField(
        _("fiscalize receipts and invoices"),
        default=False,
        help_text=_("Every sale is sent to the tax authority and gets an NSLF and NIVF code with a QR code."),
    )
    fiscal_test = models.BooleanField(
        _("use the tax authority's test system"), default=True, help_text=_("Turn off only when going live.")
    )
    fiscal_business_unit = models.CharField(
        _("business unit code"), max_length=20, blank=True, help_text=_("From the self-care portal, e.g. ab123cd456.")
    )
    fiscal_tcr_code = models.CharField(
        _("cash register (TCR) code"),
        max_length=20,
        blank=True,
        help_text=_("Used by reception and by outlets without their own cash register code."),
    )
    fiscal_software_code = models.CharField(_("software code"), max_length=20, blank=True)
    fiscal_maintainer_code = models.CharField(_("maintainer code"), max_length=20, blank=True)
    fiscal_operator_code = models.CharField(
        _("default operator code"),
        max_length=20,
        blank=True,
        help_text=_("Used for staff members who don't have their own operator code."),
    )
    fiscal_town = models.CharField(_("town"), max_length=60, blank=True, default="Tiranë")
    fiscal_certificate = models.TextField(_("digital certificate"), blank=True)
    fiscal_certificate_password = models.CharField(_("certificate password"), max_length=120, blank=True)
    vat_rate_accommodation = models.DecimalField(
        _("VAT rate for accommodation (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("6.00"),
        help_text=_("Room nights. Food, drinks and other services use the main VAT rate."),
    )
    fiscal_exchange_rate = models.DecimalField(
        _("exchange rate (lekë for 1 unit of your currency)"),
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=_("Only if prices are not in lekë (ALL), e.g. 100.50 for EUR. Use the Bank of Albania rate."),
    )
    fiscal_since = models.DateTimeField(null=True, blank=True, editable=False)  # when fiscalization was turned on

    # Automatic copies of the data to another place (USB drive, OneDrive / Google Drive folder, NAS)
    SYNC_EVERY_CHOICES = [
        (15, _("Every 15 minutes")),
        (30, _("Every 30 minutes")),
        (60, _("Every hour")),
        (240, _("Every 4 hours")),
        (1440, _("Once a day")),
    ]
    sync_enabled = models.BooleanField(
        _("copy the data to another place automatically"),
        default=False,
        help_text=_("A full copy is written there regularly, so a broken or stolen computer never loses your data."),
    )
    sync_folder = models.CharField(
        _("folder"),
        max_length=500,
        blank=True,
        help_text=_(
            "A USB drive (e.g. E:\\InnKeeper) or a folder that OneDrive, Google Drive or Dropbox keeps in the cloud."
        ),
    )
    sync_every = models.PositiveIntegerField(_("how often"), default=60, choices=SYNC_EVERY_CHOICES)
    sync_password = models.CharField(
        _("password for the copies"),
        max_length=128,
        blank=True,
        help_text=_(
            "Recommended for cloud folders: the copies are encrypted and can only be restored with this password. "
            "Write it down — without it the copies can't be opened."
        ),
    )
    sync_last_at = models.DateTimeField(null=True, blank=True, editable=False)
    sync_last_file = models.CharField(max_length=255, blank=True, editable=False)
    sync_last_error = models.CharField(max_length=500, blank=True, editable=False)
    sync_last_error_at = models.DateTimeField(null=True, blank=True, editable=False)
    sync_last_digest = models.CharField(max_length=64, blank=True, editable=False)  # skip identical copies

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
        if self.tax_status != self.TaxStatus.VAT:
            self.vat_rate = Decimal("0")
        if self.tax_status == self.TaxStatus.NONE:
            self.fiscal_enabled = False  # fiscalization is for registered businesses only
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
    def registered(self) -> bool:
        """Registered with the tax authority (has a NIPT; may fiscalize)."""
        return self.tax_status != self.TaxStatus.NONE

    @property
    def charges_vat(self) -> bool:
        return self.tax_status == self.TaxStatus.VAT and bool(self.vat_rate)

    @property
    def fiscal_on(self) -> bool:
        return self.fiscal_enabled and self.registered

    @property
    def vat_fraction(self) -> Decimal:
        """Share of a VAT-inclusive price that is VAT, e.g. 20% → 1/6."""
        return self.vat_rate / (Decimal("100") + self.vat_rate) if self.charges_vat else Decimal("0")

    @property
    def summary_recipients(self) -> list[str]:
        return [a.strip() for a in (self.summary_to or "").replace(";", ",").split(",") if a.strip()]

    @property
    def second_cash(self) -> bool:
        return bool(self.second_currency and self.second_currency_rate and self.second_currency_rate > 0)

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
    def fiscal_configured(self) -> bool:
        return bool(
            self.fiscal_on
            and self.tax_id
            and self.fiscal_business_unit
            and self.fiscal_tcr_code
            and self.fiscal_software_code
            and self.fiscal_certificate
        )

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


def csv_safe(value):
    """A cell for a CSV opened in Excel: text starting with = + - @ would run as a formula."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


class SafeCSVWriter:
    """csv.writer whose text cells can't run as Excel formulas (names come from guests and channels)."""

    def __init__(self, f, **kwargs):
        import csv

        self._w = csv.writer(f, **kwargs)

    def writerow(self, row):
        return self._w.writerow([csv_safe(v) for v in row])


def audit(user, action: str, description: str, obj=None) -> AuditLog:
    return AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        description=str(description)[:255],
        object_type=obj._meta.label if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
    )


class GroupMember(models.Model):
    """Another business of the same owner, shown on the group overview. Each business keeps its own
    InnKeeper and data; this one only reads a short summary from it with a read-only key."""

    name = models.CharField(_("name"), max_length=120)
    url = models.URLField(
        _("address"),
        help_text=_("How this computer reaches the other InnKeeper, e.g. http://100.64.1.7:8765 (Tailscale) or https://hotel.example.com"),
    )
    token = models.CharField(_("sharing key"), max_length=64, help_text=_("From the other business: Settings → Group overview."))
    sort_order = models.PositiveSmallIntegerField(_("order"), default=0)
    last_ok_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = _("business in the group")

    def __str__(self) -> str:
        return self.name
