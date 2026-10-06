"""
Role-based access control.

Each area of the app is a "module". A user may open a module when the
business has it switched on (Settings → Modules) and their role is listed
for it. Managers and superusers can open every switched-on module.
"""

from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from .models import Role

MODULE_ROLES: dict[str, set[str]] = {
    "frontdesk": {Role.RECEPTION},
    "guests": {Role.RECEPTION, Role.FINANCE},
    "housekeeping": {Role.RECEPTION, Role.HOUSEKEEPING},
    "maintenance": {Role.RECEPTION, Role.HOUSEKEEPING, Role.MAINTENANCE},
    "outlets": {Role.OUTLET, Role.RECEPTION},
    "finance": {Role.FINANCE},
    "kitchen": {Role.KITCHEN, Role.OUTLET},
    "management": set(),  # managers only
}


def module_enabled(module: str) -> bool:
    from apps.core.models import HotelSettings

    return module in HotelSettings.load().enabled_modules()


def can_access(user, module: str) -> bool:
    """True when the business uses this module and the user's role may open it."""
    if not user.is_authenticated or not user.is_active:
        return False
    if not module_enabled(module):
        return False
    if user.is_manager:
        return True
    return user.role in MODULE_ROLES.get(module, set())


def accessible_modules(user) -> set[str]:
    return {module for module in MODULE_ROLES if can_access(user, module)}


class ModuleRequiredMixin(LoginRequiredMixin):
    """Class-based view mixin: set `module = "frontdesk"` on the view."""

    module: str = ""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_access(request.user, self.module):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def module_required(module: str):
    """Function-based view decorator."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            if not can_access(request.user, module):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
