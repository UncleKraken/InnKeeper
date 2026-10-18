"""
Stock: what the business buys (ingredients, bottles, cleaning supplies, room amenities),
how much is on the shelf, and what each menu item uses up when it is sold.

Every change to a quantity is a `StockMove`, so the history explains every number.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.businessday import business_date

QTY = {"max_digits": 12, "decimal_places": 3}
MONEY = {"max_digits": 12, "decimal_places": 2}
COST = {"max_digits": 12, "decimal_places": 4}
ZERO = Decimal("0")


class Supplier(models.Model):
    name = models.CharField(_("name"), max_length=120, unique=True)
    contact = models.CharField(_("contact person"), max_length=120, blank=True)
    phone = models.CharField(_("phone"), max_length=40, blank=True)
    email = models.EmailField(_("email"), blank=True)
    tax_id = models.CharField(_("tax ID (NIPT)"), max_length=40, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("supplier")
        verbose_name_plural = _("suppliers")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class StockItem(models.Model):
    class Unit(models.TextChoices):
        PIECE = "pcs", _("piece")
        BOTTLE = "bottle", _("bottle")
        KG = "kg", _("kg")
        LITRE = "l", _("litre")
        PACK = "pack", _("pack")
        BOX = "box", _("box")
        PORTION = "portion", _("portion")

    class Group(models.TextChoices):
        FOOD = "food", _("Food")
        DRINKS = "drinks", _("Drinks")
        BAR = "bar", _("Bar & spirits")
        CLEANING = "cleaning", _("Cleaning")
        AMENITIES = "amenities", _("Room amenities & minibar")
        OTHER = "other", _("Other")

    name = models.CharField(_("name"), max_length=120, unique=True)
    group = models.CharField(_("group"), max_length=16, choices=Group.choices, default=Group.FOOD)
    unit = models.CharField(_("unit"), max_length=10, choices=Unit.choices, default=Unit.PIECE)
    on_hand = models.DecimalField(_("in stock"), default=ZERO, **QTY)
    min_level = models.DecimalField(
        _("reorder level"),
        default=ZERO,
        validators=[MinValueValidator(0)],
        help_text=_("You get a warning when stock falls to this level. 0 = no warning."),
        **QTY,
    )
    cost = models.DecimalField(
        _("cost per unit"),
        default=ZERO,
        validators=[MinValueValidator(0)],
        help_text=_("Updated automatically from deliveries (average purchase price)."),
        **COST,
    )
    supplier = models.ForeignKey(
        Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="items", verbose_name=_("supplier")
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("stock item")
        verbose_name_plural = _("stock items")
        ordering = ["group", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def value(self) -> Decimal:
        return (max(self.on_hand, ZERO) * self.cost).quantize(Decimal("0.01"))

    @property
    def is_low(self) -> bool:
        return self.min_level > 0 and self.on_hand <= self.min_level


class RecipeLine(models.Model):
    """How much of a stock item one sale of a menu item uses."""

    item = models.ForeignKey(
        "outlets.Item", on_delete=models.CASCADE, related_name="recipe", verbose_name=_("menu item")
    )
    stock_item = models.ForeignKey(
        StockItem, on_delete=models.CASCADE, related_name="used_in", verbose_name=_("stock item")
    )
    quantity = models.DecimalField(_("quantity"), validators=[MinValueValidator(Decimal("0.001"))], **QTY)

    class Meta:
        verbose_name = _("recipe line")
        verbose_name_plural = _("recipes")
        constraints = [models.UniqueConstraint(fields=["item", "stock_item"], name="unique_recipe_line")]

    def __str__(self) -> str:
        return f"{self.item}: {self.quantity} {self.stock_item.get_unit_display()} {self.stock_item}"


class Delivery(models.Model):
    supplier = models.ForeignKey(
        Supplier,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deliveries",
        verbose_name=_("supplier"),
    )
    business_date = models.DateField(_("date"), default=business_date)
    reference = models.CharField(_("invoice / reference"), max_length=80, blank=True)
    note = models.CharField(_("note"), max_length=255, blank=True)
    total = models.DecimalField(_("total"), default=ZERO, **MONEY)
    expense = models.ForeignKey(
        "finance.Expense", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name=_("expense")
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("delivery")
        verbose_name_plural = _("deliveries")
        ordering = ["-business_date", "-id"]

    def __str__(self) -> str:
        return f"{self.business_date:%d.%m.%Y} {self.supplier or ''} {self.reference}".strip()


class StockCount(models.Model):
    business_date = models.DateField(_("date"), default=business_date)
    note = models.CharField(_("note"), max_length=255, blank=True)
    difference_value = models.DecimalField(_("difference"), default=ZERO, **MONEY)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("stock count")
        verbose_name_plural = _("stock counts")
        ordering = ["-business_date", "-id"]

    def __str__(self) -> str:
        return f"{_('Stock count')} {self.business_date:%d.%m.%Y}"


class StockMove(models.Model):
    class Kind(models.TextChoices):
        DELIVERY = "delivery", _("Delivery")
        SALE = "sale", _("Sold")
        RETURN = "return", _("Sale voided")
        WASTE = "waste", _("Waste / breakage")
        COUNT = "count", _("Count correction")
        ADJUST = "adjust", _("Adjustment")

    stock_item = models.ForeignKey(StockItem, on_delete=models.CASCADE, related_name="moves")
    kind = models.CharField(_("type"), max_length=12, choices=Kind.choices)
    quantity = models.DecimalField(_("quantity"), help_text=_("Positive in, negative out."), **QTY)
    unit_cost = models.DecimalField(_("cost per unit"), default=ZERO, **COST)
    business_date = models.DateField(_("date"), default=business_date, db_index=True)
    note = models.CharField(_("note"), max_length=255, blank=True)
    order = models.ForeignKey(
        "outlets.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_moves"
    )
    delivery = models.ForeignKey(Delivery, null=True, blank=True, on_delete=models.CASCADE, related_name="moves")
    count = models.ForeignKey(StockCount, null=True, blank=True, on_delete=models.CASCADE, related_name="moves")
    balance = models.DecimalField(_("in stock after"), default=ZERO, **QTY)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("stock movement")
        verbose_name_plural = _("stock movements")
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.quantity} {self.stock_item}"

    @property
    def value(self) -> Decimal:
        return (self.quantity * self.unit_cost).quantize(Decimal("0.01"))


class PurchaseOrder(models.Model):
    """What we ask a supplier to bring. Receiving it records a delivery and updates the stock."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SENT = "sent", _("Ordered")
        RECEIVED = "received", _("Received")
        CANCELLED = "cancelled", _("Cancelled")

    supplier = models.ForeignKey(
        Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders", verbose_name=_("supplier")
    )
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.DRAFT)
    wanted_for = models.DateField(_("needed by"), null=True, blank=True)
    note = models.CharField(_("note for the supplier"), max_length=255, blank=True)
    delivery = models.ForeignKey(
        Delivery, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_orders"
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("purchase order")
        verbose_name_plural = _("purchase orders")
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{_('Order')} {self.number} {self.supplier or ''}".strip()

    @property
    def number(self) -> str:
        return f"PO-{self.pk:04d}" if self.pk else "PO"

    @property
    def is_open(self) -> bool:
        return self.status in (self.Status.DRAFT, self.Status.SENT)

    @property
    def badge(self) -> str:
        return {"draft": "closed", "sent": "warning", "received": "success", "cancelled": "danger"}[self.status]

    @property
    def total(self) -> Decimal:
        return sum((ln.total for ln in self.lines.all()), ZERO)


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name="+", verbose_name=_("item"))
    quantity = models.DecimalField(_("quantity"), validators=[MinValueValidator(Decimal("0.001"))], **QTY)
    unit_cost = models.DecimalField(_("expected price per unit"), default=ZERO, **COST)

    class Meta:
        ordering = ["id"]

    @property
    def total(self) -> Decimal:
        return (self.quantity * self.unit_cost).quantize(Decimal("0.01"))
