from django.urls import path

from . import menu

app_name = "menu"

urlpatterns = [
    path("<str:token>/", menu.public_menu, name="public"),
    path("<str:token>/print/", menu.public_menu_print, name="print"),
]
