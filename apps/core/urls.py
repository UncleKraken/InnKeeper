from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("settings/", views.hotel_settings, name="settings"),
    path("audit/", views.AuditLogView.as_view(), name="audit_log"),
    path("health/", views.health, name="health"),
]
