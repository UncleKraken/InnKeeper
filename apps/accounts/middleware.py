from django.utils import translation


class UserLanguageMiddleware:
    """Apply the signed-in user's preferred language, if they chose one."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.language:
            translation.activate(user.language)
            request.LANGUAGE_CODE = user.language
        return self.get_response(request)
