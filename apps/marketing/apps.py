from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class MarketingConfig(AppConfig):
    name = "apps.marketing"
    verbose_name = _("Contacts & marketing")
    default_auto_field = "django.db.models.BigAutoField"
