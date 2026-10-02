from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class HousekeepingConfig(AppConfig):
    name = "apps.housekeeping"
    label = "housekeeping"
    verbose_name = _("Housekeeping")
