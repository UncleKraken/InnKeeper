"""First-run setup: turns the answers from the setup wizard into a working configuration."""

from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.frontdesk.models import Room, RoomType
from apps.outlets.models import Category, Outlet, Table

from .models import HotelSettings, audit

CURRENCIES = {"EUR": "€", "ALL": "L", "USD": "$", "GBP": "£", "CHF": "CHF"}

# Starter outlets: kind → (name in Albanian, name in English, uses tables, default tables, categories)
STARTER_OUTLETS = {
    "restaurant": (
        _("Restaurant"),
        True,
        10,
        [("Antipasta", "Starters"), ("Pjata kryesore", "Mains"), ("Ëmbëlsira", "Desserts"), ("Pije", "Drinks")],
    ),
    "bar": (
        _("Bar"),
        True,
        8,
        [
            ("Kafe", "Coffee"),
            ("Pije freskuese", "Soft drinks"),
            ("Birra", "Beer"),
            ("Verë & pije alkoolike", "Wine & spirits"),
        ],
    ),
    "cafe": (_("Café"), True, 8, [("Kafe", "Coffee"), ("Çaj", "Tea"), ("Ëmbëlsira", "Pastries")]),
    "room_service": (_("Room service"), False, 0, [("Mëngjes", "Breakfast"), ("Ushqim", "Food"), ("Pije", "Drinks")]),
    "spa": (
        _("Spa & wellness"),
        False,
        0,
        [("Masazhe", "Massages"), ("Trajtime", "Treatments"), ("Sauna & hamam", "Sauna & hammam")],
    ),
    "pool": (
        _("Pool / beach"),
        True,
        12,
        [("Pije", "Drinks"), ("Snacks", "Snacks"), ("Shezlongë & çadra", "Sunbeds & umbrellas")],
    ),
    "minibar": (_("Minibar"), False, 0, [("Pije", "Drinks"), ("Snacks", "Snacks")]),
    "laundry": (_("Laundry"), False, 0, [("Larje & hekurosje", "Wash & iron")]),
    "transfer": (_("Transfers & tours"), False, 0, [("Transferta", "Transfers"), ("Ture", "Tours")]),
}

DEFAULTS_BY_TYPE = {
    HotelSettings.BusinessType.HOTEL: {
        "modules": {"rooms", "housekeeping", "maintenance", "outlets"},
        "outlets": {"restaurant", "bar", "room_service"},
        "day_ends_at": 0,
    },
    HotelSettings.BusinessType.GUESTHOUSE: {
        "modules": {"rooms", "housekeeping", "maintenance"},
        "outlets": set(),
        "day_ends_at": 0,
    },
    HotelSettings.BusinessType.RESTAURANT: {
        "modules": {"outlets", "maintenance"},
        "outlets": {"restaurant", "bar"},
        "day_ends_at": 0,
    },
    # Night bars and clubs: the night's takings belong to the evening it started.
    HotelSettings.BusinessType.NIGHTLIFE: {
        "modules": {"outlets", "maintenance"},
        "outlets": {"bar"},
        "day_ends_at": 5,
    },
}


@dataclass
class SetupAnswers:
    business_type: str
    name: str
    language: str = "sq"
    address: str = ""
    tax_id: str = ""
    phone: str = ""
    email: str = ""
    currency: str = "EUR"
    vat_rate: Decimal = Decimal("20")
    modules: set[str] = field(default_factory=set)
    floors: int = 0
    rooms_per_floor: int = 0
    room_rate: Decimal = Decimal("60")
    outlets: set[str] = field(default_factory=set)
    day_ends_at: int | None = None  # None: the usual for this type of business


def grid_positions(count: int, per_row: int = 6) -> list[tuple[int, int]]:
    """Spread new tables evenly across the 1000 × 640 floor plan."""
    return [(60 + (i % per_row) * 150, 60 + (i // per_row) * 140) for i in range(count)]


KITCHEN_CATEGORIES = {"Starters", "Mains", "Desserts", "Food", "Breakfast", "Snacks", "Pastries", "Night menu"}
DRINK_CATEGORIES = {"Drinks", "Coffee", "Soft drinks", "Beer", "Wine & spirits", "Tea"}


def starter_station(kind: str, category_en: str):
    """Food goes to the kitchen screen, drinks to the bar screen (only where someone else prepares them)."""
    from apps.outlets.models import Station

    if kind in {"restaurant", "room_service"} and category_en in KITCHEN_CATEGORIES:
        return Station.objects.get_or_create(name="Kuzhina", defaults={"sort_order": 0})[0]
    if kind in {"restaurant", "room_service", "pool"} and category_en in DRINK_CATEGORIES:
        return Station.objects.get_or_create(name="Bar", defaults={"sort_order": 1})[0]
    return None


@transaction.atomic
def apply_setup(answers: SetupAnswers, user) -> HotelSettings:
    hs = HotelSettings.load()
    hs.business_type = answers.business_type
    hs.name = answers.name.strip() or hs.name
    hs.default_language = answers.language
    hs.address = answers.address
    hs.tax_id = answers.tax_id
    hs.phone = answers.phone
    hs.email = answers.email
    hs.currency = answers.currency
    hs.currency_symbol = CURRENCIES.get(answers.currency, answers.currency)
    hs.vat_rate = answers.vat_rate
    hs.module_rooms = "rooms" in answers.modules
    hs.module_housekeeping = "housekeeping" in answers.modules and hs.module_rooms
    hs.module_maintenance = "maintenance" in answers.modules
    hs.module_outlets = "outlets" in answers.modules
    hs.day_ends_at = (
        answers.day_ends_at
        if answers.day_ends_at is not None
        else DEFAULTS_BY_TYPE.get(answers.business_type, {}).get("day_ends_at", 0)
    )
    hs.setup_completed = True
    hs.save()

    # Rooms are only generated into an empty hotel, so re-running setup never duplicates them.
    if hs.module_rooms and answers.floors and answers.rooms_per_floor and not Room.objects.exists():
        room_type, _created = RoomType.objects.get_or_create(
            code="STD", defaults={"name": str(_("Standard")), "base_rate": answers.room_rate}
        )
        for floor in range(1, answers.floors + 1):
            for n in range(1, answers.rooms_per_floor + 1):
                Room.objects.create(number=f"{floor}{n:02d}", room_type=room_type, floor=floor)

    if hs.module_outlets:
        for order, kind in enumerate(k for k in STARTER_OUTLETS if k in answers.outlets):
            if Outlet.objects.filter(kind=kind).exists():
                continue
            name, uses_tables, n_tables, categories = STARTER_OUTLETS[kind]
            outlet = Outlet.objects.create(name=str(name), kind=kind, uses_tables=uses_tables, sort_order=order)
            for i, (x, y) in enumerate(grid_positions(n_tables), start=1):
                Table.objects.create(outlet=outlet, name=str(i), seats=4, pos_x=x, pos_y=y, sort_order=i)
            for c_order, (sq, en) in enumerate(categories):
                Category.objects.create(
                    outlet=outlet, name=sq, name_en=en, sort_order=c_order, station=starter_station(kind, en)
                )

    audit(user, "settings.setup", f"{hs.name} ({hs.get_business_type_display()})", hs)
    return hs
