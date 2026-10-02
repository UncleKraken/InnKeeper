from apps.accounts.permissions import accessible_modules

from .models import HotelSettings


def innkeeper(request):
    user = getattr(request, "user", None)
    modules = accessible_modules(user) if user is not None and user.is_authenticated else set()
    return {
        "hotel": HotelSettings.load(),
        "modules": modules,
    }
