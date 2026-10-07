from django.conf import settings
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

MONEY = {"max_digits": 12, "decimal_places": 2}


class FiscalCounter(models.Model):
    """Invoice ordinal numbers: one gap-free series per cash register (TCR) and year, as the law requires."""

    tcr_code = models.CharField(max_length=20)
    year = models.PositiveSmallIntegerField()
    value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tcr_code", "year"], name="unique_fiscal_counter")]

    @classmethod
    def next(cls, tcr_code: str, year: int) -> int:
        with transaction.atomic():
            row, _created = cls.objects.select_for_update().get_or_create(tcr_code=tcr_code, year=year)
            row.value += 1
            row.save(update_fields=["value"])
            return row.value


class FiscalDocument(models.Model):
    """One fiscalized invoice (receipt or guest bill) with everything that was sent and what came back."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting to be sent")
        REGISTERED = "registered", _("Registered")
        FAILED = "failed", _("Rejected")

    class Kind(models.TextChoices):
        RECEIPT = "receipt", _("Receipt")
        INVOICE = "invoice", _("Guest bill")
        CORRECTION = "correction", _("Correction")

    kind = models.CharField(_("type"), max_length=12, choices=Kind.choices)
    order = models.ForeignKey(
        "outlets.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="fiscal_documents"
    )
    folio = models.ForeignKey(
        "finance.Folio", null=True, blank=True, on_delete=models.PROTECT, related_name="fiscal_documents"
    )
    corrects = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="corrections", verbose_name=_("corrects")
    )
    type_of_inv = models.CharField(max_length=8)  # CASH / NONCASH
    tcr_code = models.CharField(_("cash register"), max_length=20)
    business_unit = models.CharField(max_length=20)
    operator_code = models.CharField(max_length=20)
    software_code = models.CharField(max_length=20)
    inv_ord_num = models.PositiveIntegerField()
    inv_num = models.CharField(_("invoice number"), max_length=60)
    issue_datetime = models.CharField(max_length=40)  # exactly as signed, e.g. 2026-10-07T20:30:00+02:00
    total = models.DecimalField(_("total"), **MONEY)
    iic = models.CharField("NSLF", max_length=32, db_index=True)
    iic_signature = models.CharField(max_length=512)
    fic = models.CharField("NIVF", max_length=40, blank=True)
    status = models.CharField(_("status"), max_length=12, choices=Status.choices, default=Status.PENDING)
    was_offline = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(_("problem"), blank=True)
    test = models.BooleanField(default=False)
    payload = models.JSONField(default=dict)  # the data the XML is built from, so it can be re-sent unchanged
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    registered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("fiscal document")
        verbose_name_plural = _("fiscal documents")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.inv_num

    @property
    def nslf(self) -> str:
        return self.iic

    @property
    def nivf(self) -> str:
        return self.fic

    @property
    def verify_url(self) -> str:
        from .cis import verify_url

        return verify_url(self)


class CashDeposit(models.Model):
    """Cash in the drawer reported to the tax authority: the opening amount each day, and withdrawals."""

    class Operation(models.TextChoices):
        INITIAL = "INITIAL", _("Opening cash")
        WITHDRAW = "WITHDRAW", _("Cash taken out")

    business_date = models.DateField(_("date"), db_index=True)
    tcr_code = models.CharField(_("cash register"), max_length=20)
    operation = models.CharField(_("operation"), max_length=10, choices=Operation.choices)
    amount = models.DecimalField(_("amount"), **MONEY)
    change_datetime = models.CharField(max_length=40)
    fcdc = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=12, default="pending")
    last_error = models.TextField(blank=True)
    test = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("cash deposit")
        verbose_name_plural = _("cash deposits")
        ordering = ["-created_at"]
