from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class StaffConfig(AppConfig):
    name = "apps.staff"
    label = "staff"
    verbose_name = _("Staff time & schedule")
