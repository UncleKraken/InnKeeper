from django.urls import path

from . import views

app_name = "marketing"

urlpatterns = [
    path("", views.contacts, name="contacts"),
    path("sync/", views.sync, name="sync"),
    path("new/", views.contact_form, name="contact_create"),
    path("<int:pk>/", views.contact_form, name="contact_edit"),
    path("campaigns/", views.campaigns, name="campaigns"),
    path("campaigns/new/", views.campaign_form, name="campaign_create"),
    path("campaigns/<int:pk>/", views.campaign_detail, name="campaign_detail"),
    path("campaigns/<int:pk>/edit/", views.campaign_form, name="campaign_edit"),
    path("campaigns/<int:pk>/send/", views.campaign_send, name="campaign_send"),
    path("sign-up-qr/", views.signup_poster, name="signup_poster"),
]
