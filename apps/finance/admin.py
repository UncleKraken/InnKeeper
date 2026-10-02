from django.contrib import admin

from .models import Charge, Folio, Payment


class ReadOnlyLedgerAdmin(admin.ModelAdmin):
    """The ledger is changed only through the app (with audit trail), never here."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Folio)
class FolioAdmin(ReadOnlyLedgerAdmin):
    list_display = ("number", "reservation", "status")


@admin.register(Charge)
class ChargeAdmin(ReadOnlyLedgerAdmin):
    list_display = ("business_date", "description", "amount", "kind", "voided")
    list_filter = ("kind", "voided")


@admin.register(Payment)
class PaymentAdmin(ReadOnlyLedgerAdmin):
    list_display = ("business_date", "method", "amount", "voided")
    list_filter = ("method", "voided")
