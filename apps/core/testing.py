"""Shared test fixtures: a tiny hotel with one room type, two rooms, staff and a restaurant."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.frontdesk.models import Guest, Reservation, Room, RoomType
from apps.outlets.models import Category, Item, Outlet, Table

PASSWORD = "a-strong-test-pass-91"


class HotelTestCase(TestCase):
    @classmethod
    def _pre_setup(cls):
        from apps.core.models import clear_settings_cache

        super()._pre_setup()
        clear_settings_cache()  # settings are cached per thread; each test starts from the database

    @classmethod
    def setUpTestData(cls):
        from apps.core.models import HotelSettings

        cls.today = timezone.localdate()
        hs = HotelSettings.load()
        hs.setup_completed = True
        hs.save()
        cls.manager = User.objects.create_user("boss", password=PASSWORD, role=Role.MANAGER)
        cls.reception = User.objects.create_user("desk", password=PASSWORD, role=Role.RECEPTION)
        cls.waiter = User.objects.create_user("waiter", password=PASSWORD, role=Role.OUTLET)
        cls.cleaner = User.objects.create_user("cleaner", password=PASSWORD, role=Role.HOUSEKEEPING)
        cls.accountant = User.objects.create_user("money", password=PASSWORD, role=Role.FINANCE)

        cls.double = RoomType.objects.create(
            name="Double", code="DBL", base_rate=Decimal("80.00"), max_adults=2, max_children=1
        )
        cls.room = Room.objects.create(number="101", room_type=cls.double, floor=1)
        cls.room2 = Room.objects.create(number="102", room_type=cls.double, floor=1)
        cls.guest = Guest.objects.create(first_name="Ana", last_name="Koci")

        cls.restaurant = Outlet.objects.create(name="Restaurant", kind=Outlet.Kind.RESTAURANT)
        cls.table = Table.objects.create(outlet=cls.restaurant, name="1")
        mains = Category.objects.create(outlet=cls.restaurant, name="Mains")
        cls.dish = Item.objects.create(category=mains, name="Tavë kosi", price=Decimal("11.00"))
        cls.wine = Item.objects.create(category=mains, name="Wine", price=Decimal("4.50"))

    def make_reservation(self, *, room=None, start=0, nights=2, status=Reservation.Status.BOOKED, save=True):
        from apps.frontdesk import services

        res = Reservation(
            guest=self.guest,
            room=room or self.room,
            arrival=self.today + timedelta(days=start),
            departure=self.today + timedelta(days=start + nights),
            adults=2,
            rate=Decimal("80.00"),
        )
        services.save_reservation(res, self.reception)
        if status != Reservation.Status.BOOKED:
            Reservation.objects.filter(pk=res.pk).update(status=status)
            res.refresh_from_db()
        return res
