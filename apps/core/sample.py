"""
Sample data: a full demo hotel with a restaurant, bar and spa, so a new user sees every screen working
in one minute. Only offered on an empty system, and removed with one button before going live.
"""

from django.db import transaction

from .models import HotelSettings, audit, clear_settings_cache

PREFIX = "sample."


def is_empty() -> bool:
    from apps.finance.models import Charge, Payment
    from apps.frontdesk.models import Reservation, Room
    from apps.outlets.models import Item, Order

    return not any(m.objects.exists() for m in (Room, Reservation, Item, Order, Charge, Payment))


@transaction.atomic
def load(user) -> None:
    from apps.core.management.commands.seed_demo import create_demo

    from .exceptions import BusinessError

    if not is_empty():
        raise BusinessError("not-empty")
    language = HotelSettings.load().default_language
    create_demo(None, prefix=PREFIX)  # sample staff can't sign in
    HotelSettings.objects.filter(pk=1).update(
        demo_data=True, fiscal_enabled=False, default_language=language, business_type="hotel"
    )
    clear_settings_cache()
    audit(user, "sample.load", "Sample data added")


@transaction.atomic
def remove(user) -> None:
    """Delete all the sample data (and anything typed in while trying it) and start the setup again.

    Staff accounts people created themselves are kept, so they can still sign in."""
    from apps.accounts.models import User
    from apps.fiscal.models import FiscalDocument

    from . import backup
    from .exceptions import BusinessError

    hs = HotelSettings.load()
    if not hs.demo_data:
        raise BusinessError("not-sample")
    language = hs.default_language
    FiscalDocument.objects.exclude(corrects=None).delete()
    for model in reversed(backup._models(backup.FULL_MODELS)):
        if model is not User:
            model._default_manager.all().delete()
    User.objects.filter(username__startswith=PREFIX).delete()
    clear_settings_cache()
    fresh = HotelSettings.load()
    fresh.default_language = language
    fresh.save()
    clear_settings_cache()
    audit(user, "sample.remove", "Sample data removed")
