from django.contrib import admin

from .models import CashDeposit, FiscalDocument


@admin.register(FiscalDocument)
class FiscalDocumentAdmin(admin.ModelAdmin):
    list_display = ["created_at", "inv_num", "kind", "total", "status", "iic", "fic"]
    list_filter = ["status", "kind", "test"]
    readonly_fields = [f.name for f in FiscalDocument._meta.fields]


@admin.register(CashDeposit)
class CashDepositAdmin(admin.ModelAdmin):
    list_display = ["created_at", "tcr_code", "operation", "amount", "status"]
    readonly_fields = [f.name for f in CashDeposit._meta.fields]
