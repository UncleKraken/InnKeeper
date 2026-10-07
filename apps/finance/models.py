"""
The money ledger.

* A **Folio** is a guest's bill for a stay (one per reservation).
* A **Charge** is revenue: room nights, an outlet order, or an extra.
  Charges posted to a folio are paid later; outlet orders paid on the spot
  have a charge with no folio.
* A **Payment** is money received, against a folio or an outlet order.

Nothing in the ledger is ever deleted: mistakes are voided with a reason,
so the history always adds up.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

MONEY = {"max_digits": 12, "decimal_places": 2}
ZERO = Decimal("0.00")


class Folio(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        CLOSED = "closed", _("Closed")

    reservation = models.OneToOneField(
        "frontdesk.Reservation", on_delete=models.PROTECT, related_name="folio", verbose_name=_("reservation")
    )
    status = models.CharField(_("status"), max_length=8, choices=Status.choices, default=Status.OPEN)
    invoice_number = models.CharField(_("invoice number"), max_length=20, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("folio")
        verbose_name_plural = _("folios")
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"F{self.pk:06d}"

    @property
    def number(self) -> str:
        return f"F{self.pk:06d}"

    @property
    def total_charges(self) -> Decimal:
        return self.charges.filter(voided=False).aggregate(t=Sum("amount"))["t"] or ZERO

    @property
    def total_payments(self) -> Decimal:
        return self.payments.filter(voided=False).aggregate(t=Sum("amount"))["t"] or ZERO

    @property
    def balance(self) -> Decimal:
        return self.total_charges - self.total_payments

    def accommodation_nights_posted(self) -> int:
        value = self.charges.filter(kind=Charge.Kind.ACCOMMODATION, voided=False).aggregate(n=Sum("quantity"))["n"]
        return int(value or 0)


class VoidableQuerySet(models.QuerySet):
    def active(self):
        return self.filter(voided=False)


class LedgerEntry(models.Model):
    business_date = models.DateField(_("date"), default=timezone.localdate, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    voided = models.BooleanField(_("voided"), default=False)
    void_reason = models.CharField(_("void reason"), max_length=255, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)

    objects = VoidableQuerySet.as_manager()

    class Meta:
        abstract = True


class Charge(LedgerEntry):
    class Kind(models.TextChoices):
        ACCOMMODATION = "accommodation", _("Accommodation")
        OUTLET = "outlet", _("Outlet")
        EXTRA = "extra", _("Extra")

    folio = models.ForeignKey(Folio, null=True, blank=True, on_delete=models.PROTECT, related_name="charges")
    order = models.ForeignKey("outlets.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="charges")
    outlet = models.ForeignKey(
        "outlets.Outlet",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="charges",
        verbose_name=_("outlet"),
    )
    kind = models.CharField(_("type"), max_length=16, choices=Kind.choices)
    description = models.CharField(_("description"), max_length=200)
    quantity = models.PositiveIntegerField(_("quantity"), default=1)
    unit_price = models.DecimalField(_("unit price"), **MONEY)
    amount = models.DecimalField(_("amount"), **MONEY)

    class Meta:
        verbose_name = _("charge")
        verbose_name_plural = _("charges")
        ordering = ["business_date", "id"]

    def __str__(self) -> str:
        return f"{self.description} {self.amount}"

    def save(self, *args, **kwargs):
        self.amount = (self.unit_price * self.quantity).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    @property
    def department(self) -> str:
        if self.kind == self.Kind.ACCOMMODATION:
            return str(_("Accommodation"))
        if self.outlet_id:
            return self.outlet.name
        return str(_("Extras"))


class Payment(LedgerEntry):
    class Method(models.TextChoices):
        CASH = "cash", _("Cash")
        CARD = "card", _("Card")
        BANK_TRANSFER = "bank_transfer", _("Bank transfer")
        ONLINE = "online", _("Online card payment")
        OTHER = "other", _("Other")

    folio = models.ForeignKey(Folio, null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    order = models.ForeignKey("outlets.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    method = models.CharField(_("method"), max_length=16, choices=Method.choices, default=Method.CASH)
    amount = models.DecimalField(_("amount"), **MONEY)
    reference = models.CharField(_("reference"), max_length=80, blank=True)
    tendered = models.DecimalField(_("cash given"), null=True, blank=True, **MONEY)

    class Meta:
        verbose_name = _("payment")
        verbose_name_plural = _("payments")
        ordering = ["business_date", "id"]

    def __str__(self) -> str:
        return f"{self.get_method_display()} {self.amount}"

    @property
    def change(self) -> Decimal:
        return max((self.tendered or ZERO) - self.amount, ZERO) if self.tendered else ZERO


class Expense(LedgerEntry):
    """Money going out: supplies, salaries, bills… so the owner can see real profit."""

    class Category(models.TextChoices):
        FOOD_DRINK = "food_drink", _("Food & drink stock")
        SUPPLIES = "supplies", _("Supplies & cleaning")
        SALARIES = "salaries", _("Salaries")
        UTILITIES = "utilities", _("Electricity, water, internet")
        RENT = "rent", _("Rent")
        MAINTENANCE = "maintenance", _("Repairs & maintenance")
        MARKETING = "marketing", _("Marketing & commissions")
        TAXES = "taxes", _("Taxes & fees")
        OTHER = "other", _("Other")

    category = models.CharField(_("category"), max_length=16, choices=Category.choices, default=Category.SUPPLIES)
    description = models.CharField(_("description"), max_length=200)
    supplier = models.CharField(_("supplier"), max_length=120, blank=True)
    amount = models.DecimalField(_("amount"), **MONEY)
    method = models.CharField(
        _("paid with"), max_length=16, choices=Payment.Method.choices, default=Payment.Method.CASH
    )
    reference = models.CharField(_("invoice / reference"), max_length=80, blank=True)

    class Meta:
        verbose_name = _("expense")
        verbose_name_plural = _("expenses")
        ordering = ["-business_date", "-id"]

    def __str__(self) -> str:
        return f"{self.description} {self.amount}"


class DayClose(models.Model):
    """End-of-day cash count (Z report). Records what the drawer should hold and what was counted."""

    business_date = models.DateField(_("date"), unique=True)
    opening_float = models.DecimalField(_("opening float"), default=ZERO, **MONEY)
    cash_sales = models.DecimalField(_("cash received"), **MONEY)
    cash_expenses = models.DecimalField(_("cash paid out"), **MONEY)
    expected_cash = models.DecimalField(_("expected in drawer"), **MONEY)
    counted_cash = models.DecimalField(_("counted"), **MONEY)
    card_total = models.DecimalField(_("card"), default=ZERO, **MONEY)
    other_total = models.DecimalField(_("bank & other"), default=ZERO, **MONEY)
    revenue_total = models.DecimalField(_("revenue"), default=ZERO, **MONEY)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    closed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("day close")
        verbose_name_plural = _("day closes")
        ordering = ["-business_date"]

    def __str__(self) -> str:
        return f"Z {self.business_date}"

    @property
    def difference(self) -> Decimal:
        return self.counted_cash - self.expected_cash
