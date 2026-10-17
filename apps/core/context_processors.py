from apps.accounts.permissions import accessible_modules

from .models import HotelSettings


def innkeeper(request):
    user = getattr(request, "user", None)
    modules = accessible_modules(user) if user is not None and user.is_authenticated else set()
    update = None
    if user is not None and user.is_authenticated and user.is_manager:
        from .updates import update_available

        update = update_available()
    from apps import __version__

    my_shift = None
    if user is not None and user.is_authenticated and "outlets" in modules:
        from apps.finance.tabs import open_shift_for

        my_shift = open_shift_for(user)
    return {
        "my_shift": my_shift,
        "hotel": HotelSettings.load(),
        "modules": modules,
        "update_available": update,
        "innkeeper_version": __version__,
    }
