from django.shortcuts import redirect
from django.urls import reverse

from .models import HotelSettings, clear_settings_cache

SETUP_EXEMPT_PREFIXES = ("/setup/", "/static/", "/accounts/", "/i18n/", "/health/", "/admin/", "/menu/")


class SettingsCacheMiddleware:
    """Load hotel settings fresh for every request (one query), so changes show everywhere at once."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_settings_cache()
        try:
            return self.get_response(request)
        finally:
            clear_settings_cache()


class SetupRequiredMiddleware:
    """Send managers to the setup wizard until the business has been set up."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and user.is_manager
            and not request.path.startswith(SETUP_EXEMPT_PREFIXES)
            and not HotelSettings.load().setup_completed
        ):
            return redirect(reverse("core:setup"))
        return self.get_response(request)
