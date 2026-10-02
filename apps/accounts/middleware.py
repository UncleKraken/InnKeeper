from django.conf import settings
from django.utils import translation


class UserLanguageMiddleware:
    """Language order: the user's own choice, then the language cookie, then the business default."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from apps.core.models import HotelSettings

        user = getattr(request, "user", None)
        lang = None
        if user is not None and user.is_authenticated and user.language:
            lang = user.language
        elif settings.LANGUAGE_COOKIE_NAME not in request.COOKIES:
            lang = HotelSettings.load().default_language
        if lang:
            translation.activate(lang)
            request.LANGUAGE_CODE = lang
        return self.get_response(request)
