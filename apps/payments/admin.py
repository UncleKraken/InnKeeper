from django.contrib import admin

from .models import PaymentLink


@admin.register(PaymentLink)
class PaymentLinkAdmin(admin.ModelAdmin):
    list_display = ["created_at", "description", "amount", "currency", "provider", "status"]
    list_filter = ["status", "provider"]
    readonly_fields = [f.name for f in PaymentLink._meta.fields]
