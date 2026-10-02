from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class OutletsConfig(AppConfig):
    name = "apps.outlets"
    label = "outlets"
    verbose_name = _("Outlets")
