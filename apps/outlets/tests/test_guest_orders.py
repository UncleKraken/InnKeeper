import json
from decimal import Decimal as D

from django.core.cache import cache
from django.urls import reverse

from apps.core.testing import PASSWORD, HotelTestCase
from apps.outlets.models import GuestRequest, Option, OptionGroup, Order, OrderLine, Station


class TableOrderingTests(HotelTestCase):
    def setUp(self):
        cache.clear()
        self.restaurant.qr_ordering = True
        self.restaurant.save()
        self.table.refresh_from_db()
        self.url = reverse("menu:table", args=[self.table.qr_token])

    def send(self, cart, **extra):
        return self.client.post(self.url, {"kind": "order", "cart": json.dumps(cart), **extra})

    def test_every_table_has_its_own_code(self):
        self.assertTrue(self.table.qr_token)
        r = self.client.get(self.url)
        self.assertContains(r, "Tavë kosi")
        self.assertContains(r, self.table.name)

    def test_off_or_unknown_is_not_found(self):
        self.assertEqual(self.client.get(reverse("menu:table", args=["nope"])).status_code, 404)
        self.restaurant.qr_ordering = False
        self.restaurant.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_order_waits_for_staff_then_goes_on_the_bill(self):
        r = self.send([{"item": self.dish.pk, "quantity": 2}, {"item": self.wine.pk, "quantity": 1, "note": "cold"}], note="birthday")
        self.assertEqual(r.status_code, 302)
        req = GuestRequest.objects.get()
        self.assertEqual(req.total, D("26.50"))
        self.assertFalse(Order.objects.exists())  # nothing on a bill yet

        r = self.client.get(self.url)
        self.assertContains(r, f'data-req="{req.pk}"')  # this phone sees its order

        self.client.login(username="waiter", password=PASSWORD)
        self.assertContains(self.client.get(reverse("outlets:guest_requests")), "Tavë kosi")
        self.assertEqual(self.client.get(reverse("outlets:guest_requests_count")).json()["count"], 1)
        r = self.client.post(reverse("outlets:guest_request_accept", args=[req.pk]))
        order = Order.objects.get()
        self.assertRedirects(r, reverse("outlets:order", args=[order.pk]), fetch_redirect_response=False)
        self.assertEqual(order.table, self.table)
        self.assertEqual(order.total, D("26.50"))
        self.assertIn("birthday", order.note)
        req.refresh_from_db()
        self.assertEqual(req.status, GuestRequest.Status.ACCEPTED)
        self.assertEqual(req.order, order)
        # Answered once only.
        self.client.post(reverse("outlets:guest_request_accept", args=[req.pk]))
        self.assertEqual(order.lines.count(), 2)

        # The guest's phone (its cookie) sees the answer.
        self.assertEqual(self.client.get(reverse("menu:table_status", args=[self.table.qr_token])).json()["requests"], {str(req.pk): "accepted"})

    def test_adds_to_the_table_open_bill_and_sends_to_the_kitchen(self):
        station = Station.objects.create(name="Kitchen")
        self.dish.category.station = station
        self.dish.category.save()
        from apps.outlets import services as pos

        existing = pos.open_order(self.restaurant, user=self.waiter, table=self.table)
        self.send([{"item": self.dish.pk, "quantity": 1}])
        self.client.login(username="waiter", password=PASSWORD)
        self.client.post(reverse("outlets:guest_request_accept", args=[GuestRequest.objects.get().pk]))
        self.assertEqual(Order.objects.count(), 1)
        line = existing.lines.get()
        self.assertEqual(line.status, OrderLine.Status.SENT)

    def test_options_are_checked(self):
        size = OptionGroup.objects.create(name="Size", required=True)
        size.items.add(self.wine)
        big = Option.objects.create(group=size, name="Large", price_change=D("1.50"))
        r = self.send([{"item": self.wine.pk, "quantity": 1}])
        self.assertEqual(r.status_code, 200)  # required choice missing
        self.assertFalse(GuestRequest.objects.exists())
        self.send([{"item": self.wine.pk, "quantity": 1, "options": [big.pk]}])
        self.assertEqual(GuestRequest.objects.get().total, D("6.00"))

    def test_rejects_foreign_or_sold_out_items_and_silly_amounts(self):
        self.wine.is_active = False
        self.wine.save()
        for cart in ([{"item": self.wine.pk, "quantity": 1}], [{"item": 99999, "quantity": 1}], [{"item": self.dish.pk, "quantity": 500}], []):
            self.assertEqual(self.send(cart).status_code, 200)
        self.assertFalse(GuestRequest.objects.exists())

    def test_call_waiter_once_and_limits(self):
        self.client.post(self.url, {"kind": "waiter"})
        self.client.post(self.url, {"kind": "waiter"})
        self.assertEqual(GuestRequest.objects.filter(kind="waiter").count(), 1)
        for _i in range(6):
            self.send([{"item": self.dish.pk, "quantity": 1}])
        self.assertEqual(GuestRequest.objects.filter(kind="order").count(), 5)  # at most 5 waiting per table
        self.client.login(username="waiter", password=PASSWORD)
        self.client.post(reverse("outlets:guest_request_accept", args=[GuestRequest.objects.get(kind="waiter").pk]))
        self.assertEqual(GuestRequest.objects.get(kind="waiter").status, GuestRequest.Status.DONE)

    def test_decline_with_reason(self):
        self.send([{"item": self.dish.pk, "quantity": 1}])
        req = GuestRequest.objects.get()
        self.client.login(username="waiter", password=PASSWORD)
        self.client.post(reverse("outlets:guest_request_decline", args=[req.pk]), {"reason": "Kitchen closed"})
        req.refresh_from_db()
        self.assertEqual((req.status, req.reason), ("declined", "Kitchen closed"))
        self.assertFalse(Order.objects.exists())

    def test_staff_of_other_outlets_dont_see_it(self):
        from apps.accounts.models import Role, User

        other = User.objects.create_user("bar", password=PASSWORD, role=Role.OUTLET)
        bar = self.restaurant.__class__.objects.create(name="Bar")
        bar.staff.add(other)
        self.restaurant.staff.add(self.waiter)
        self.send([{"item": self.dish.pk, "quantity": 1}])
        self.client.login(username="bar", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("outlets:guest_requests_count")).json()["count"], 0)
        r = self.client.post(reverse("outlets:guest_request_accept", args=[GuestRequest.objects.get().pk]))
        self.assertEqual(r.status_code, 404)

    def test_print_codes_and_new_codes(self):
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.get(reverse("outlets:table_qr_cards", args=[self.restaurant.pk]))
        self.assertContains(r, "<svg")
        old = self.table.qr_token
        self.client.post(reverse("outlets:new_table_codes", args=[self.restaurant.pk]))
        self.table.refresh_from_db()
        self.assertNotEqual(old, self.table.qr_token)
        self.assertEqual(self.client.get(reverse("menu:table", args=[old])).status_code, 404)

    def test_floor_shows_the_table_asking(self):
        self.client.post(self.url, {"kind": "bill"})
        self.client.login(username="waiter", password=PASSWORD)
        self.assertContains(self.client.get(reverse("outlets:floor", args=[self.restaurant.pk])), "p-asking")
        self.assertContains(self.client.get("/"), "guest-req-badge")
