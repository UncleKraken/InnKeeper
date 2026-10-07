from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("paysera/callback/", views.paysera_callback, name="paysera_callback"),
    path("pok/<str:token>/", views.pok_webhook, name="pok_webhook"),
    path("staff/reservation/<int:pk>/", views.create_for_reservation, name="create_for_reservation"),
    path("staff/link/<int:pk>/", views.link_action, name="link_action"),
    path("<str:token>/", views.pay, name="pay"),
    path("<str:token>/done/", views.done, name="done"),
]
