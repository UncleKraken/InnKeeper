import secrets
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Sum
from django.utils.translation import gettext_lazy as _

MONEY = {"max_digits": 12, "decimal_places": 2}


class Printer(models.Model):
    """A receipt or kitchen printer (ESC/POS thermal printers, the usual kind in shops and kitchens)."""

    class Connection(models.TextChoices):
        NETWORK = "network", _("Network (IP address)")
        SYSTEM = "system", _("Installed on this computer (USB)")

    name = models.CharField(_("name"), max_length=60, help_text=_("e.g. Bar receipt printer, Kitchen printer"))
    connection = models.CharField(
        _("connection"), max_length=10, choices=Connection.choices, default=Connection.NETWORK
    )
    address = models.CharField(
        _("IP address"),
        max_length=100,
        blank=True,
        help_text=_("Printed on the printer's self-test page, e.g. 192.168.1.50"),
    )
    port = models.PositiveIntegerField(_("port"), default=9100)
    system_name = models.CharField(
        _("printer name in Windows"),
        max_length=120,
        blank=True,
        help_text=_("Exactly as shown in Windows Settings → Printers. Works only on the computer running InnKeeper."),
    )
    paper_width = models.PositiveSmallIntegerField(_("paper width"), choices=[(58, "58 mm"), (80, "80 mm")], default=80)
    open_drawer = models.BooleanField(
        _("open cash drawer on cash payments"),
        default=False,
        help_text=_("For a cash drawer plugged into this printer."),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("printer")
        verbose_name_plural = _("printers")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def where(self) -> str:
        if self.connection == self.Connection.NETWORK:
            return f"{self.address}:{self.port}"
        return self.system_name


class Station(models.Model):
    """Where orders are prepared: Kitchen, Bar, Pizza oven… Each has a screen and/or a printer."""

    name = models.CharField(_("name"), max_length=60)
    printer = models.ForeignKey(
        Printer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stations",
        verbose_name=_("ticket printer"),
        help_text=_("Optional. New orders are printed here as well as shown on the screen."),
    )
    sort_order = models.PositiveSmallIntegerField(_("order"), default=0)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("station")
        verbose_name_plural = _("stations")
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class Outlet(models.Model):
    """Any point of sale or service in the hotel: restaurant, bar, spa, room service, laundry…"""

    class Kind(models.TextChoices):
        RESTAURANT = "restaurant", _("Restaurant")
        BAR = "bar", _("Bar")
        CAFE = "cafe", _("Café")
        ROOM_SERVICE = "room_service", _("Room service")
        MINIBAR = "minibar", _("Minibar")
        SPA = "spa", _("Spa & wellness")
        POOL = "pool", _("Pool / beach")
        LAUNDRY = "laundry", _("Laundry")
        TRANSFER = "transfer", _("Transfers & tours")
        EVENTS = "events", _("Events & conferences")
        OTHER = "other", _("Other service")

    name = models.CharField(_("name"), max_length=80)
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices, default=Kind.RESTAURANT)
    uses_tables = models.BooleanField(
        _("uses tables"), default=True, help_text=_("Turn off for services without tables, e.g. spa or laundry.")
    )
    staff = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="outlets",
        verbose_name=_("staff"),
        help_text=_("Service staff who can use this outlet. Leave empty to allow all service staff."),
    )
    sort_order = models.PositiveSmallIntegerField(_("order"), default=0)
    is_active = models.BooleanField(_("active"), default=True)
    menu_public = models.BooleanField(
        _("public menu"), default=True, help_text=_("Guests can open this menu on their phone by scanning a QR code.")
    )
    menu_intro = models.CharField(_("menu introduction"), max_length=255, blank=True)
    menu_token = models.CharField(max_length=24, unique=True, editable=False, default="")
    receipt_printer = models.ForeignKey(
        Printer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="outlets",
        verbose_name=_("receipt printer"),
        help_text=_("Bills and receipts print here. Leave empty to print from the browser."),
    )
    auto_print_receipt = models.BooleanField(
        _("print a receipt for every payment"), default=False, help_text=_("Needs a receipt printer.")
    )

    class Meta:
        verbose_name = _("outlet")
        verbose_name_plural = _("outlets")
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.menu_token:
            self.menu_token = secrets.token_urlsafe(9)
        super().save(*args, **kwargs)

    def user_can_use(self, user) -> bool:
        if user.is_manager or user.role != "outlet":
            return True
        return not self.staff.exists() or self.staff.filter(pk=user.pk).exists()


class Category(models.Model):
    outlet = models.ForeignKey(Outlet, on_delete=models.CASCADE, related_name="categories", verbose_name=_("outlet"))
    name = models.CharField(_("name"), max_length=80)
    name_en = models.CharField(_("name in English"), max_length=80, blank=True)
    station = models.ForeignKey(
        Station,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="categories",
        verbose_name=_("prepared at"),
        help_text=_("Where items in this category are prepared. Leave empty for things served straight away."),
    )
    sort_order = models.PositiveSmallIntegerField(_("order"), default=0)

    class Meta:
        verbose_name = _("category")
        verbose_name_plural = _("categories")
        ordering = ["outlet", "sort_order", "name"]

    def __str__(self) -> str:
        return f"{self.outlet} · {self.name}"


class Item(models.Model):
    """A product or service sold by an outlet (a dish, a drink, a massage, a laundry piece…)."""

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="items", verbose_name=_("category"))
    name = models.CharField(_("name"), max_length=120)
    name_en = models.CharField(_("name in English"), max_length=120, blank=True)
    description = models.CharField(_("description"), max_length=255, blank=True)
    description_en = models.CharField(_("description in English"), max_length=255, blank=True)
    price = models.DecimalField(_("price"), validators=[MinValueValidator(0)], **MONEY)
    duration_minutes = models.PositiveSmallIntegerField(
        _("duration (minutes)"), null=True, blank=True, help_text=_("For services such as a massage.")
    )
    sort_order = models.PositiveSmallIntegerField(_("order"), default=0)
    is_active = models.BooleanField(_("available"), default=True)

    class Meta:
        verbose_name = _("item")
        verbose_name_plural = _("items")
        ordering = ["category", "sort_order", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def outlet(self) -> Outlet:
        return self.category.outlet


class Table(models.Model):
    class Shape(models.TextChoices):
        SQUARE = "square", _("Square")
        ROUND = "round", _("Round")
        LONG = "long", _("Long")

    outlet = models.ForeignKey(Outlet, on_delete=models.CASCADE, related_name="tables", verbose_name=_("outlet"))
    name = models.CharField(_("name"), max_length=30, help_text=_("e.g. 1, 2, Terrace 4, Sunbed 12"))
    seats = models.PositiveSmallIntegerField(_("seats"), default=4)
    zone = models.CharField(_("area"), max_length=40, blank=True, help_text=_("e.g. Inside, Terrace, Garden"))
    shape = models.CharField(_("shape"), max_length=8, choices=Shape.choices, default=Shape.SQUARE)
    # Position on the floor plan, in plan units (the plan is 1000 × 640).
    pos_x = models.PositiveSmallIntegerField(default=0)
    pos_y = models.PositiveSmallIntegerField(default=0)
    width = models.PositiveSmallIntegerField(default=90)
    height = models.PositiveSmallIntegerField(default=90)
    sort_order = models.PositiveSmallIntegerField(_("order"), default=0)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("table")
        verbose_name_plural = _("tables")
        ordering = ["outlet", "sort_order", "id"]
        constraints = [models.UniqueConstraint(fields=["outlet", "name"], name="unique_table_name_per_outlet")]

    def __str__(self) -> str:
        return self.name

    def open_order(self):
        return self.orders.filter(status=Order.Status.OPEN).first()


class Order(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        CLOSED = "closed", _("Closed")
        CANCELLED = "cancelled", _("Cancelled")

    class Settlement(models.TextChoices):
        PAID = "paid", _("Paid")
        ROOM = "room", _("Charged to room")

    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="orders", verbose_name=_("outlet"))
    table = models.ForeignKey(
        Table, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders", verbose_name=_("table")
    )
    label = models.CharField(
        _("label"), max_length=80, blank=True, help_text=_("Customer name or note for orders without a table.")
    )
    guests = models.PositiveSmallIntegerField(_("guests"), default=1)
    note = models.CharField(_("note"), max_length=255, blank=True)
    status = models.CharField(_("status"), max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    settlement = models.CharField(_("settlement"), max_length=8, choices=Settlement.choices, blank=True)
    discount = models.DecimalField(_("discount"), default=Decimal("0.00"), **MONEY)
    discount_reason = models.CharField(_("discount reason"), max_length=120, blank=True)
    receipt_number = models.CharField(_("receipt number"), max_length=20, blank=True, db_index=True)

    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+", verbose_name=_("opened by")
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("order")
        verbose_name_plural = _("orders")
        ordering = ["-opened_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["table"], condition=models.Q(status="open"), name="one_open_order_per_table"
            )
        ]

    def __str__(self) -> str:
        return f"#{self.pk} {self.outlet}"

    @property
    def number(self) -> str:
        return f"{self.pk:06d}" if self.pk else "—"

    @property
    def display_name(self) -> str:
        if self.table_id:
            return _("Table %(name)s") % {"name": self.table.name}
        return self.label or _("Order #%(n)s") % {"n": self.number}

    @property
    def active_lines(self):
        """Lines still on the bill (items cancelled after going to the kitchen have quantity 0)."""
        return self.lines.filter(quantity__gt=0)

    @property
    def unsent_count(self) -> int:
        return self.lines.filter(status=OrderLine.Status.NEW, quantity__gt=0).count()

    @property
    def subtotal(self) -> Decimal:
        value = self.lines.aggregate(t=Sum(F("unit_price") * F("quantity")))["t"]
        return (value or Decimal("0")).quantize(Decimal("0.01"))

    @property
    def total(self) -> Decimal:
        return max(self.subtotal - self.discount, Decimal("0.00"))

    @property
    def paid(self) -> Decimal:
        value = self.payments.filter(voided=False).aggregate(t=Sum("amount"))["t"]
        return value or Decimal("0.00")

    @property
    def remaining(self) -> Decimal:
        return max(self.total - self.paid, Decimal("0.00"))

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.OPEN


class KitchenTicket(models.Model):
    """One batch of items sent to one station. Shown on the station's screen until it is served."""

    class Status(models.TextChoices):
        NEW = "new", _("New")
        PREPARING = "preparing", _("Preparing")
        READY = "ready", _("Ready")
        SERVED = "served", _("Served")
        CANCELLED = "cancelled", _("Cancelled")

    ON_BOARD = (Status.NEW, Status.PREPARING, Status.READY, Status.CANCELLED)

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="tickets")
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name="tickets")
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    sent_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    served_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sent_at", "id"]

    def __str__(self) -> str:
        return f"{self.station} · {self.order.display_name}"


class OrderLine(models.Model):
    class Status(models.TextChoices):
        NEW = "new", _("Not sent")
        SENT = "sent", _("Sent")
        DIRECT = "direct", _("Served directly")

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, null=True, on_delete=models.SET_NULL, related_name="+")
    # Name and price are copied so old bills stay correct after the menu changes.
    name = models.CharField(_("name"), max_length=120)
    unit_price = models.DecimalField(_("unit price"), **MONEY)
    quantity = models.PositiveSmallIntegerField(_("quantity"), default=1)
    note = models.CharField(_("note"), max_length=120, blank=True)
    station = models.ForeignKey(Station, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DIRECT)
    ticket = models.ForeignKey(KitchenTicket, null=True, blank=True, on_delete=models.SET_NULL, related_name="lines")
    sent_quantity = models.PositiveSmallIntegerField(default=0)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["added_at", "id"]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.name}"

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity

    @property
    def is_new(self) -> bool:
        return self.status == self.Status.NEW


class PrintJob(models.Model):
    """Everything sent to a printer is kept for a few days, so failed jobs can be retried."""

    class Status(models.TextChoices):
        DONE = "done", _("Printed")
        FAILED = "failed", _("Failed")

    printer = models.ForeignKey(Printer, on_delete=models.CASCADE, related_name="jobs")
    title = models.CharField(max_length=120)
    data = models.BinaryField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.FAILED)
    error = models.CharField(max_length=255, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title
