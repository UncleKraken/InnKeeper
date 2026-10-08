from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from .models import HotelSettings, clear_settings_cache

SETUP_EXEMPT_PREFIXES = (
    "/setup/",
    "/static/",
    "/accounts/",
    "/i18n/",
    "/health/",
    "/admin/",
    "/menu/",
    "/help/",
    "/book/",
    "/ical/",
    "/pay/",
    "/channex/",
)


LOOPBACK = {"127.0.0.1", "::1"}


def client_ip(request) -> str:
    """The visitor's address. A tunnel running on this computer (Cloudflare Tunnel) connects from
    127.0.0.1, so for those requests the address the tunnel reports is used instead."""
    if request is None:
        return "-"
    remote = request.META.get("REMOTE_ADDR", "-")
    if remote in LOOPBACK:
        forwarded = request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("HTTP_X_FORWARDED_FOR", "")
        forwarded = forwarded.split(",")[0].strip()
        if forwarded:
            return forwarded[:64]
    return remote


class SecureCookieMiddleware:
    """Mark the session and CSRF cookies Secure whenever the page came over HTTPS (e.g. through the
    tunnel), even though the Windows app also serves plain HTTP on the local network."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.is_secure():
            for name in (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
                if name in response.cookies:
                    response.cookies[name]["secure"] = True
        return response


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
