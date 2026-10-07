from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class FrontDeskConfig(AppConfig):
    name = "apps.frontdesk"
    label = "frontdesk"
    verbose_name = _("Front desk")

    def ready(self):
        from . import signals  # noqa: F401
