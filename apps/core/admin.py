from django.contrib import admin

from .models import AuditLog, HotelSettings

admin.site.register(HotelSettings)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "description")
    list_filter = ("action",)
    search_fields = ("description",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
