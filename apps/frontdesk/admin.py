from django.contrib import admin

from .models import Guest, Reservation, Room, RoomType

admin.site.register(RoomType)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("number", "room_type", "floor", "hk_status", "out_of_order", "is_active")
    list_filter = ("room_type", "floor", "hk_status")


@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "phone", "email", "nationality")
    search_fields = ("first_name", "last_name", "phone", "email", "document_number")


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ("code", "guest", "room", "arrival", "departure", "status")
    list_filter = ("status", "source")
    search_fields = ("guest__first_name", "guest__last_name")
    raw_id_fields = ("guest",)
