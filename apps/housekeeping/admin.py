from django.contrib import admin

from .models import HousekeepingTask, MaintenanceTicket


@admin.register(HousekeepingTask)
class HousekeepingTaskAdmin(admin.ModelAdmin):
    list_display = ("room", "kind", "status", "assigned_to", "due_date")
    list_filter = ("status", "kind")


@admin.register(MaintenanceTicket)
class MaintenanceTicketAdmin(admin.ModelAdmin):
    list_display = ("title", "room", "priority", "status", "created_at")
    list_filter = ("status", "priority")
