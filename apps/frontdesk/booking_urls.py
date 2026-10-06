from django.urls import path

from . import public

app_name = "booking"

urlpatterns = [
    path("", public.search, name="search"),
    path("room/<int:type_id>/", public.details, name="details"),
    path("r/<str:token>/", public.status, name="status"),
]
