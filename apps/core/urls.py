from django.urls import path

from . import settings_views, views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("settings/", settings_views.settings_hub, name="settings"),
    path("settings/backup/<str:kind>.innkeeper", settings_views.backup_download, name="backup_download"),
    path("settings/backup/save/", settings_views.backup_now, name="backup_now"),
    path("settings/backup/file/<str:name>", settings_views.backup_file, name="backup_file"),
    path("settings/restore/", settings_views.restore, name="restore"),
    path("settings/email/test/", settings_views.email_test, name="email_test"),
    path("settings/restore/confirm/", settings_views.restore_confirm, name="restore_confirm"),
    path("setup/", views.setup_wizard, name="setup"),
    path("setup/done/", views.setup_done, name="setup_done"),
    path("audit/", views.AuditLogView.as_view(), name="audit_log"),
    path("health/", views.health, name="health"),
    path("help/", views.help_center, name="help"),
    path("welcome/dismiss/", views.dismiss_onboarding, name="dismiss_onboarding"),
]
