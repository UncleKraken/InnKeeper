from decimal import Decimal

from apps.core.exceptions import BusinessError
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Charge, Payment
from apps.frontdesk.models import Reservation
from apps.outlets import services
from apps.outlets.models import Order


class OrderTests(HotelTestCase):
    def test_table_has_only_one_open_order(self):
        first = services.open_order(self.restaurant, table=self.table, user=self.waiter)
        again = services.open_order(self.restaurant, table=self.table, user=self.waiter)
        self.assertEqual(first.pk, again.pk)

    def test_adding_the_same_item_increases_quantity_and_prices_are_snapshotted(self):
        order = services.open_order(self.restaurant, table=self.table, user=self.waiter)
        services.add_item(order, self.dish, user=self.waiter)
        line = services.add_item(order, self.dish, user=self.waiter)
        self.assertEqual(line.quantity, 2)
        self.dish.price = Decimal("99")
        self.dish.save()
        self.assertEqual(order.total, Decimal("22.00"))

    def test_pay_order_records_revenue_and_payment_and_frees_table(self):
        order = services.open_order(self.restaurant, table=self.table, user=self.waiter)
        services.add_item(order, self.dish, user=self.waiter)
        services.add_item(order, self.wine, user=self.waiter, quantity=2)
        services.pay_order(order, method="card", user=self.waiter)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(Charge.objects.get(order=order).amount, Decimal("20.00"))
        self.assertEqual(Payment.objects.get(order=order).amount, Decimal("20.00"))
        self.assertIsNone(self.table.open_order())
        with self.assertRaises(BusinessError):
            services.add_item(order, self.dish, user=self.waiter)

    def test_charge_to_room_lands_on_the_guest_bill(self):
        res = self.make_reservation(status=Reservation.Status.CHECKED_IN)
        order = services.open_order(self.restaurant, table=self.table, user=self.waiter)
        services.add_item(order, self.dish, user=self.waiter)
        services.charge_to_room(order, res, user=self.waiter)
        self.assertEqual(res.folio.balance, Decimal("11.00"))
        self.assertFalse(Payment.objects.filter(order=order).exists())

    def test_cannot_charge_to_a_guest_who_is_not_in_house(self):
        res = self.make_reservation()  # booked, not arrived
        order = services.open_order(self.restaurant, table=self.table, user=self.waiter)
        services.add_item(order, self.dish, user=self.waiter)
        with self.assertRaises(BusinessError):
            services.charge_to_room(order, res, user=self.waiter)

    def test_empty_orders_cannot_be_paid(self):
        order = services.open_order(self.restaurant, table=self.table, user=self.waiter)
        with self.assertRaises(BusinessError):
            services.pay_order(order, method="cash", user=self.waiter)

    def test_only_manager_cancels_orders_with_items(self):
        order = services.open_order(self.restaurant, table=self.table, user=self.waiter)
        services.add_item(order, self.dish, user=self.waiter)
        with self.assertRaises(BusinessError):
            services.cancel_order(order, user=self.waiter)
        services.cancel_order(order, user=self.manager)

    def test_removing_last_quantity_deletes_line(self):
        order = services.open_order(self.restaurant, table=self.table, user=self.waiter)
        line = services.add_item(order, self.dish, user=self.waiter)
        self.assertIsNone(services.change_quantity(line, -1, user=self.waiter))
        self.assertEqual(order.lines.count(), 0)

    def test_outlet_staff_restriction(self):
        bar = self.restaurant.__class__.objects.create(name="Bar", kind="bar")
        self.assertTrue(bar.user_can_use(self.waiter))  # no staff list = everyone
        bar.staff.add(self.cleaner)
        self.assertFalse(bar.user_can_use(self.waiter))


class InPlaceOrderTests(HotelTestCase):
    """The till updates the bill without reloading (phones keep their place in the menu)."""

    def setUp(self):
        from apps.outlets import services as pos

        self.client.login(username="waiter", password=PASSWORD)
        self.order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)

    def post(self, url, data):
        return self.client.post(url, data, HTTP_X_REQUESTED_WITH="fetch")

    def test_adding_an_item_returns_the_new_bill(self):
        from django.urls import reverse

        r = self.post(reverse("outlets:add_item", args=[self.order.pk]), {"item": self.dish.pk})
        data = r.json()
        self.assertIn("Tavë kosi", data["ticket"])
        self.assertIn("11.00", data["bar"])
        self.assertEqual(data["error"], "")
        line = self.order.lines.get()
        r = self.post(reverse("outlets:change_line", args=[self.order.pk, line.pk]), {"delta": "1"})
        self.assertIn("22.00", r.json()["bar"])

    def test_problems_come_back_as_a_message(self):
        from django.urls import reverse

        self.post(reverse("outlets:add_item", args=[self.order.pk]), {"item": self.dish.pk})
        self.dish.is_active = False
        self.dish.save()
        line = self.order.lines.get()
        data = self.post(reverse("outlets:change_line", args=[self.order.pk, line.pk]), {"delta": "1"}).json()
        self.assertTrue(data["error"])

    def test_without_javascript_the_page_reloads(self):
        from django.urls import reverse

        r = self.client.post(reverse("outlets:add_item", args=[self.order.pk]), {"item": self.dish.pk})
        self.assertRedirects(r, reverse("outlets:order", args=[self.order.pk]), fetch_redirect_response=False)
