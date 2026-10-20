from decimal import Decimal as D

from django.urls import reverse

from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Folio
from apps.frontdesk import breakfast
from apps.frontdesk.models import BreakfastServed, Reservation
from apps.housekeeping import minibar
from apps.outlets.models import Category, Item, Order, Outlet


class BreakfastTests(HotelTestCase):
    def setUp(self):
        hs = HotelSettings.load()
        hs.breakfast_on, hs.breakfast_price, hs.breakfast_included_default = True, D("8.00"), True
        hs.save()

    def in_house(self, room=None, **kw):
        res = self.make_reservation(room=room, start=-1, nights=2, status=Reservation.Status.CHECKED_IN)
        Folio.objects.get_or_create(reservation=res)
        Reservation.objects.filter(pk=res.pk).update(**kw)
        res.refresh_from_db()
        return res

    def test_list_only_guests_who_slept_here(self):
        stayed = self.in_house()
        arriving = self.make_reservation(room=self.room2, start=0, nights=1)
        rows = breakfast.guests_for(self.today)
        self.assertEqual([r.pk for r in rows], [stayed.pk])
        self.assertNotIn(arriving.pk, [r.pk for r in rows])

    def test_included_is_free_and_not_included_is_charged(self):
        free = self.in_house()
        paying = self.in_house(room=self.room2, breakfast=False)
        breakfast.serve(free, self.today, 2, self.reception)
        breakfast.serve(paying, self.today, 2, self.reception)
        self.assertEqual(free.folio.charges.count(), 0)
        c = paying.folio.charges.get()
        self.assertEqual((c.amount, c.kind), (D("16.00"), "extra"))
        with self.assertRaises(BusinessError):
            breakfast.serve(free, self.today, 2, self.reception)  # once a morning

    def test_default_follows_settings_until_set(self):
        res = self.in_house()
        self.assertTrue(res.breakfast_included)
        hs = HotelSettings.load()
        hs.breakfast_included_default = False
        hs.save()
        res.refresh_from_db()
        self.assertFalse(res.breakfast_included)
        Reservation.objects.filter(pk=res.pk).update(breakfast=True)
        res.refresh_from_db()
        self.assertTrue(res.breakfast_included)

    def test_undo_voids_the_charge_only_for_the_same_person_or_a_manager(self):
        res = self.in_house(breakfast=False)
        served = breakfast.serve(res, self.today, 1, self.reception)
        with self.assertRaises(BusinessError):
            breakfast.undo(served, self.waiter)
        breakfast.undo(served, self.reception)
        self.assertEqual(res.folio.balance, D("0"))
        self.assertFalse(BreakfastServed.objects.exists())

    def test_page_for_restaurant_staff_too(self):
        res = self.in_house(breakfast=False)
        self.client.login(username="waiter", password=PASSWORD)
        r = self.client.get(reverse("frontdesk:breakfast"))
        self.assertContains(r, self.room.number)
        self.client.post(reverse("frontdesk:breakfast_serve", args=[res.pk]), {"guests": "2", "date": self.today.isoformat()})
        self.assertEqual(res.folio.balance, D("16.00"))
        self.client.login(username="cleaner", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("frontdesk:breakfast")).status_code, 403)

    def test_booking_form_has_the_switch(self):
        self.client.login(username="desk", password=PASSWORD)
        r = self.client.get(reverse("frontdesk:reservation_create"))
        self.assertContains(r, 'name="breakfast"')


class MinibarTests(HotelTestCase):
    def setUp(self):
        self.mb = Outlet.objects.create(name="Minibar", kind=Outlet.Kind.MINIBAR, uses_tables=False)
        cat = Category.objects.create(outlet=self.mb, name="Drinks")
        self.water = Item.objects.create(category=cat, name="Water", price=D("2.00"))
        self.beer = Item.objects.create(category=cat, name="Beer", price=D("3.50"))

    def test_housekeeper_charges_the_room(self):
        res = self.make_reservation(start=-1, nights=2, status=Reservation.Status.CHECKED_IN)
        Folio.objects.get_or_create(reservation=res)
        self.client.login(username="cleaner", password=PASSWORD)
        self.assertContains(self.client.get(reverse("housekeeping:board") + "?show=all"), reverse("housekeeping:minibar", args=[self.room.pk]))
        r = self.client.post(reverse("housekeeping:minibar", args=[self.room.pk]), {f"q{self.water.pk}": "2", f"q{self.beer.pk}": "1"})
        self.assertRedirects(r, reverse("housekeeping:board"), fetch_redirect_response=False)
        self.assertEqual(res.folio.balance, D("7.50"))
        order = Order.objects.get(outlet=self.mb)
        self.assertEqual(order.settlement, Order.Settlement.ROOM)

    def test_empty_room_or_nothing_taken(self):
        with self.assertRaises(BusinessError):
            minibar.charge(self.room, {self.water.pk: 1}, self.cleaner)
        self.make_reservation(start=-1, nights=2, status=Reservation.Status.CHECKED_IN)
        with self.assertRaises(BusinessError):
            minibar.charge(self.room, {self.water.pk: 0}, self.cleaner)
        self.assertFalse(Order.objects.filter(outlet=self.mb).exists())

    def test_not_a_minibar_item(self):
        self.make_reservation(start=-1, nights=2, status=Reservation.Status.CHECKED_IN)
        with self.assertRaises(BusinessError):
            minibar.charge(self.room, {self.dish.pk: 1}, self.cleaner)
