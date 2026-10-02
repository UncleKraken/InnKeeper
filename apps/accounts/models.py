from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    MANAGER = "manager", _("Manager")
    RECEPTION = "reception", _("Reception")
    HOUSEKEEPING = "housekeeping", _("Housekeeping")
    MAINTENANCE = "maintenance", _("Maintenance")
    OUTLET = "outlet", _("Service staff (restaurant, bar, spa…)")
    FINANCE = "finance", _("Finance")


class User(AbstractUser):
    """Staff account. Passwords are hashed by Django; never stored in plain text."""

    role = models.CharField(_("role"), max_length=20, choices=Role.choices, default=Role.RECEPTION)
    phone = models.CharField(_("phone"), max_length=40, blank=True)
    language = models.CharField(
        _("language"),
        max_length=8,
        blank=True,
        choices=[("sq", _("Albanian")), ("en", _("English"))],
        help_text=_("Interface language for this user. Leave empty to use the hotel default."),
    )

    class Meta:
        verbose_name = _("staff member")
        verbose_name_plural = _("staff")
        ordering = ["first_name", "last_name", "username"]

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    @property
    def is_manager(self) -> bool:
        return self.is_superuser or self.role == Role.MANAGER
