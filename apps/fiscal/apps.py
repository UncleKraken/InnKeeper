from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class FiscalConfig(AppConfig):
    name = "apps.fiscal"
    label = "fiscal"
    verbose_name = _("Fiscalization")
