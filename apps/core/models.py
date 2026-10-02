from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.utils.translation import gettext_lazy as _


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

    class Meta:
        verbose_name = _("hotel settings")
        verbose_name_plural = _("hotel settings")

    def __str__(self) -> str:
        return self.name

    CACHE_KEY = "innkeeper:hotel-settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    def delete(self, *args, **kwargs):  # the settings row is never deleted
        return

    @classmethod
    def load(cls) -> "HotelSettings":
        obj = cache.get(cls.CACHE_KEY)
        if obj is None:
            obj, _created = cls.objects.get_or_create(pk=1)
            cache.set(cls.CACHE_KEY, obj, 300)
        return obj


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
