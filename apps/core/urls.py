from django.urls import path

from . import about, group, settings_views, views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("settings/", settings_views.settings_hub, name="settings"),
    path("settings/backup/<str:kind>.innkeeper", settings_views.backup_download, name="backup_download"),
    path("settings/backup/save/", settings_views.backup_now, name="backup_now"),
    path("settings/backup/file/<str:name>", settings_views.backup_file, name="backup_file"),
    path("settings/restore/", settings_views.restore, name="restore"),
    path("settings/restore/from-copy/", settings_views.restore_from_copy, name="restore_from_copy"),
    path("settings/copies/", settings_views.sync_settings, name="sync_settings"),
    path("settings/copies/now/", settings_views.sync_now, name="sync_now"),
    path("settings/email/test/", settings_views.email_test, name="email_test"),
    path("settings/email/summary/", settings_views.summary_settings, name="summary_settings"),
    path("settings/email/summary/send/", settings_views.summary_send_now, name="summary_send_now"),
    path("settings/restore/confirm/", settings_views.restore_confirm, name="restore_confirm"),
    path("settings/import/", settings_views.import_file, name="import_file"),
    path("settings/import/<str:kind>.csv", settings_views.import_template, name="import_template"),
    path("setup/", views.setup_wizard, name="setup"),
    path("setup/done/", views.setup_done, name="setup_done"),
    path("setup/sample/", views.sample_load, name="sample_load"),
    path("setup/sample/remove/", views.sample_remove, name="sample_remove"),
    path("audit/", views.AuditLogView.as_view(), name="audit_log"),
    path("health/", views.health, name="health"),
    path("group/", group.overview, name="group"),
    path("group/summary/", group.shared_summary, name="group_summary"),
    path("group/month/", group.shared_month, name="group_month_shared"),
    path("group/month-report/", group.month_report, name="group_month"),
    path("group/add/", group.member_form, name="group_add"),
    path("group/<int:pk>/", group.member_form, name="group_edit"),
    path("settings/group/share/", group.sharing, name="group_sharing"),
    path("update/", views.update_page, name="update"),
    path("update/install/", views.update_install, name="update_install"),
    path("update/status/", views.update_status, name="update_status"),
    path("help/", views.help_center, name="help"),
    path("about/", about.about, name="about"),
    path("welcome/dismiss/", views.dismiss_onboarding, name="dismiss_onboarding"),
]
