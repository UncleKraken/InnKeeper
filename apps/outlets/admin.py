from django.contrib import admin

from .models import Category, Item, Order, OrderLine, Outlet, Table

admin.site.register([Outlet, Category, Table])


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "is_active")
    list_filter = ("category__outlet", "is_active")
    search_fields = ("name",)


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "outlet", "table", "status", "settlement", "opened_at")
    list_filter = ("outlet", "status")
    inlines = [OrderLineInline]
