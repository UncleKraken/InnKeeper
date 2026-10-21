from django.urls import path

from . import checkin, public

app_name = "booking"

urlpatterns = [
    path("", public.search, name="search"),
    path("room/<int:type_id>/", public.details, name="details"),
    path("r/<str:token>/", public.status, name="status"),
    path("r/<str:token>/pay/", public.pay_deposit, name="pay_deposit"),
    path("checkin/<str:token>/", checkin.guest_page, name="checkin"),
]
