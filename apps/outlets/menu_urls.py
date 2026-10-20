from django.urls import path

from . import guest_orders, menu

app_name = "menu"

urlpatterns = [
    path("t/<str:token>/", guest_orders.table_page, name="table"),
    path("t/<str:token>/status/", guest_orders.table_status, name="table_status"),
    path("<str:token>/", menu.public_menu, name="public"),
    path("<str:token>/print/", menu.public_menu_print, name="print"),
]
