import secrets
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

MONEY = {"max_digits": 12, "decimal_places": 2}


def new_token() -> str:
    return secrets.token_urlsafe(18)


class PaymentLink(models.Model):
    """A request for a card payment, paid by the guest on the provider's secure page."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for payment")
        PAID = "paid", _("Paid")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    class Purpose(models.TextChoices):
        DEPOSIT = "deposit", _("Deposit")
        BALANCE = "balance", _("Payment of the bill")
        OTHER = "other", _("Other")

    token = models.CharField(max_length=40, unique=True, default=new_token)
    reservation = models.ForeignKey(
        "frontdesk.Reservation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_links",
        verbose_name=_("reservation"),
    )
    purpose = models.CharField(_("for"), max_length=10, choices=Purpose.choices, default=Purpose.DEPOSIT)
    description = models.CharField(_("description"), max_length=200)
    amount = models.DecimalField(_("amount"), **MONEY)
    currency = models.CharField(_("currency"), max_length=3)
    provider = models.CharField(_("provider"), max_length=12)
    test_mode = models.BooleanField(default=False)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.PENDING)
    external_id = models.CharField(max_length=120, blank=True, db_index=True)
    checkout_url = models.URLField(max_length=1000, blank=True)
    payment = models.ForeignKey(
        "finance.Payment", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name=_("payment")
    )
    error = models.CharField(max_length=255, blank=True)
    email = models.EmailField(_("guest email"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("payment link")
        verbose_name_plural = _("payment links")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.description} {self.amount} {self.currency}"

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.PENDING

    @property
    def minor_units(self) -> int:
        return int((self.amount * 100).quantize(Decimal("1")))
