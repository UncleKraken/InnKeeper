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
    from apps.accounts.pin import is_shared_till

    clocked_in = None
    if user is not None and user.is_authenticated:
        from apps.staff.services import open_entry

        clocked_in = open_entry(user)
    guest_requests = None
    if "outlets" in modules:
        from apps.outlets.models import Outlet

        if Outlet.objects.filter(qr_ordering=True, is_active=True).exists():
            from apps.outlets.guest_orders import pending_for

            guest_requests = len(pending_for(user))
    staff_requests = swap_offers = 0
    if user is not None and user.is_authenticated:
        from apps.staff.models import SwapRequest

        swap_offers = SwapRequest.objects.filter(to_user=user, status=SwapRequest.Status.ASKED).count()
        if "management" in modules:
            from apps.staff.requests import waiting_for_managers

            staff_requests = waiting_for_managers()
    has_group = False
    if "management" in modules:
        from .models import GroupMember

        has_group = GroupMember.objects.exists()
    return {
        "has_group": has_group,
        "staff_requests": staff_requests,
        "swap_offers": swap_offers,
        "guest_requests": guest_requests,
        "clocked_in": clocked_in,
        "shared_till": is_shared_till(request),
        "my_shift": my_shift,
        "hotel": HotelSettings.load(),
        "modules": modules,
        "update_available": update,
        "innkeeper_version": __version__,
    }
