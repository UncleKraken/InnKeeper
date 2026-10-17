from datetime import time, timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.core.exceptions import BusinessError
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Payment
from apps.outlets import bookings
from apps.outlets import services as pos
from apps.outlets.models import Category, Item, Order, Outlet, Table, TableBooking

D = Decimal


class BookingTests(HotelTestCase):
    def book(self, at="20:00", table=None, day=None, **extra):
        b = TableBooking(
            outlet=self.restaurant,
            table=table if table is not None else self.table,
            date=day or self.today,
            time=time.fromisoformat(at),
            party_size=extra.pop("party_size", 4),
            name=extra.pop("name", "Dritan"),
            **extra,
        )
        return bookings.save_booking(b, self.waiter)

    def test_overlapping_bookings_on_one_table_are_refused(self):
        self.book("20:00")  # default length is two hours
        with self.assertRaises(BusinessError):
            self.book("21:30", name="Elira")
        self.book("22:00", name="Elira")  # starts as the first one ends
        other = Table.objects.create(outlet=self.restaurant, name="2")
        self.book("21:00", table=other, name="Fatos")

    def test_late_booking_clashes_with_the_next_day(self):
        self.book("23:30")
        with self.assertRaises(BusinessError):
            self.book("00:30", day=self.today + timedelta(days=1), name="Night")

    def test_after_midnight_belongs_to_the_night_before(self):
        from apps.core.models import HotelSettings, clear_settings_cache

        s = HotelSettings.load()
        s.day_ends_at = 5
        s.save()
        clear_settings_cache()
        self.addCleanup(clear_settings_cache)
        b = self.book("01:30")
        self.assertEqual(timezone.localtime(b.starts_at).date(), self.today + timedelta(days=1))
        self.book("21:00", name="Early")  # ends 23:00, before the 01:30 table
        with self.assertRaises(BusinessError):
            self.book("00:30", name="Late")  # same night, overlaps 01:30

    def test_cancelled_bookings_free_the_table(self):
        first = self.book("20:00")
        bookings.set_status(first, TableBooking.Status.CANCELLED, self.waiter)
        self.book("20:30", name="Elira")

    def test_seat_opens_the_bill(self):
        b = self.book("20:00", party_size=6, note="Birthday")
        order = bookings.seat(b, self.waiter)
        b.refresh_from_db()
        self.assertEqual((b.status, b.order), (TableBooking.Status.SEATED, order))
        self.assertEqual((order.table, order.guests, order.note), (self.table, 6, "Birthday"))
        with self.assertRaises(BusinessError):
            bookings.seat(b, self.waiter)

    def test_seat_needs_a_free_table(self):
        pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        with self.assertRaises(BusinessError):
            bookings.seat(self.book("20:00"), self.waiter)
        no_table = TableBooking.objects.create(
            outlet=self.restaurant, date=self.today, time=time(21), party_size=2, name="Walk"
        )
        with self.assertRaises(BusinessError):
            bookings.seat(no_table, self.waiter)

    def test_floor_shows_upcoming_bookings(self):
        soon = timezone.localtime() + timedelta(hours=1)
        self.book(f"{soon:%H:%M}", day=soon.date(), name="Gentiana")
        found = bookings.upcoming_by_table(self.restaurant)
        self.assertEqual(found[self.table.pk].name, "Gentiana")

    def test_minimum_spend(self):
        b = self.book("20:00", minimum_spend=D("50"))
        order = bookings.seat(b, self.waiter)
        pos.add_item(order, self.dish, user=self.waiter, quantity=2)  # 22
        self.assertEqual(bookings.minimum_spend_left(order), D("28.00"))
        line = bookings.top_up_minimum_spend(order, self.waiter)
        self.assertEqual(line.unit_price, D("28.00"))
        order.refresh_from_db()
        self.assertEqual(order.total, D("50.00"))
        with self.assertRaises(BusinessError):
            bookings.top_up_minimum_spend(order, self.waiter)
        pos.pay_order(order, method="cash", user=self.waiter)  # the line without an item closes like any other

    def test_pages(self):
        self.client.login(username="waiter", password=PASSWORD)
        url = reverse("outlets:booking_create", args=[self.restaurant.pk])
        r = self.client.post(
            url,
            {
                "date": self.today.isoformat(),
                "time": "20:00",
                "party_size": "3",
                "name": "Klea",
                "phone": "",
                "table": str(self.table.pk),
                "duration_minutes": "120",
                "minimum_spend": "",
                "note": "",
            },
        )
        self.assertEqual(r.status_code, 302)
        listing = self.client.get(r["Location"])
        self.assertContains(listing, "Klea")
        b = TableBooking.objects.get(name="Klea")
        r = self.client.post(reverse("outlets:booking_action", args=[self.restaurant.pk, b.pk]), {"action": "seat"})
        b.refresh_from_db()
        self.assertRedirects(r, reverse("outlets:order", args=[b.order.pk]), fetch_redirect_response=False)
        self.client.login(username="cleaner", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("outlets:bookings", args=[self.restaurant.pk])).status_code, 403)


class QuickSaleTests(HotelTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.door = Outlet.objects.create(name="Door", kind=Outlet.Kind.BAR, quick_sale=True)
        cat = Category.objects.create(outlet=cls.door, name="Entrance")
        cls.ticket = Item.objects.create(category=cat, name="Entrance", price=D("10.00"))

    def test_one_tap_sells_and_takes_payment(self):
        self.client.login(username="waiter", password=PASSWORD)
        url = reverse("outlets:quick_sell", args=[self.door.pk])
        self.client.post(url, {"item": self.ticket.pk, "method": "card"})
        self.client.post(url, {"item": self.ticket.pk, "method": "cash", "quantity": "2"})
        orders = Order.objects.filter(outlet=self.door)
        self.assertEqual(set(orders.values_list("status", flat=True)), {Order.Status.CLOSED})
        self.assertEqual(
            sorted(Payment.objects.filter(order__outlet=self.door).values_list("method", "amount")),
            [("card", D("10.00")), ("cash", D("20.00"))],
        )
        page = self.client.get(reverse("outlets:floor", args=[self.door.pk]))
        self.assertEqual(page.context["sold_total"], 3)
        self.assertContains(page, "qs-btn")

    def test_items_from_other_outlets_are_refused(self):
        self.client.login(username="waiter", password=PASSWORD)
        r = self.client.post(reverse("outlets:quick_sell", args=[self.door.pk]), {"item": self.dish.pk})
        self.assertEqual(r.status_code, 404)
