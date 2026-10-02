from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class StaffAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "role", "is_active", "last_login")
    list_filter = ("role", "is_active")
    fieldsets = UserAdmin.fieldsets + (("InnKeeper", {"fields": ("role", "phone", "language")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("InnKeeper", {"fields": ("role", "first_name", "last_name")}),)
