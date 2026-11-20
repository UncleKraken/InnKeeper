"""The till screens, step by step as a waiter and a manager use them (the services have their own tests)."""

from decimal import Decimal

from django.urls import reverse

from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Payment
from apps.outlets.models import Order, OrderLine, Table


class TillTestCase(HotelTestCase):
    def setUp(self):
        from django.conf import settings

        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
        self.client.login(username="waiter", password=PASSWORD)

    def open_order(self, table=None):
        r = self.client.get(reverse("outlets:open_table", args=[self.restaurant.pk, (table or self.table).pk]))
        self.assertEqual(r.status_code, 302)
        return Order.objects.get(pk=int(r["Location"].rstrip("/").split("/")[-1]))

    def add(self, order, item, fetch=True):
        headers = {"HTTP_X_REQUESTED_WITH": "fetch"} if fetch else {}
        return self.client.post(reverse("outlets:add_item", args=[order.pk]), {"item": item.pk}, **headers)

    def settle(self, order, follow=False, **data):
        return self.client.post(reverse("outlets:settle", args=[order.pk]), data, follow=follow)


class OrderingTests(TillTestCase):
    def test_floor_and_menu_pages(self):
        # With one outlet, the till opens straight on its floor plan.
        self.assertRedirects(self.client.get(reverse("outlets:home")), reverse("outlets:floor", args=[self.restaurant.pk]), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("outlets:floor", args=[self.restaurant.pk])), self.table.name)
        order = self.open_order()
        r = self.client.get(reverse("outlets:order", args=[order.pk]))
        self.assertContains(r, "Tavë kosi")
        # Opening the same table again goes to the same bill, not a second one.
        self.assertEqual(self.open_order().pk, order.pk)

    def test_takeaway_order_with_a_name(self):
        r = self.client.post(reverse("outlets:new_order", args=[self.restaurant.pk]), {"label": "Arben"})
        order = Order.objects.get(label="Arben")
        self.assertRedirects(r, reverse("outlets:order", args=[order.pk]), fetch_redirect_response=False)

    def test_add_items_with_fetch_returns_the_bill_and_without_reloads(self):
        order = self.open_order()
        j = self.add(order, self.dish).json()
        self.assertIn("Tavë kosi", j["ticket"])
        self.assertFalse(j.get("error"))
        r = self.add(order, self.wine, fetch=False)
        self.assertRedirects(r, reverse("outlets:order", args=[order.pk]), fetch_redirect_response=False)
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal("15.50"))

    def test_change_quantity_and_remove_a_line(self):
        order = self.open_order()
        self.add(order, self.dish)
        line = order.lines.get()
        url = reverse("outlets:change_line", args=[order.pk, line.pk])
        self.client.post(url, {"delta": "2"}, HTTP_X_REQUESTED_WITH="fetch")
        line.refresh_from_db()
        self.assertEqual(line.quantity, 3)
        j = self.client.post(url, {"delta": "abc"}, HTTP_X_REQUESTED_WITH="fetch").json()
        self.assertTrue(j["error"])
        self.client.post(url, {"delta": "-3"}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertFalse(OrderLine.objects.filter(pk=line.pk, quantity__gt=0).exists())

    def test_guests_and_note(self):
        order = self.open_order()
        self.client.post(reverse("outlets:update_order", args=[order.pk]), {"guests": "4", "note": "No nuts"})
        order.refresh_from_db()
        self.assertEqual((order.guests, order.note), (4, "No nuts"))
        self.client.post(reverse("outlets:update_order", args=[order.pk]), {"guests": "zero", "note": "x" * 300})
        order.refresh_from_db()
        self.assertEqual(order.guests, 4)
        self.assertEqual(len(order.note), 255)

    def test_send_then_go_back_to_the_floor(self):
        order = self.open_order()
        self.add(order, self.dish)
        r = self.client.post(reverse("outlets:send", args=[order.pk]), {"then": "floor"})
        self.assertRedirects(r, reverse("outlets:floor", args=[self.restaurant.pk]), fetch_redirect_response=False)

    def test_move_to_another_table(self):
        other = Table.objects.create(outlet=self.restaurant, name="2")
        order = self.open_order()
        self.add(order, self.dish)
        self.client.post(reverse("outlets:move", args=[order.pk]), {"table": other.pk})
        order.refresh_from_db()
        self.assertEqual(order.table, other)

    def test_cancel_an_empty_order(self):
        order = self.open_order()
        r = self.client.post(reverse("outlets:cancel", args=[order.pk]))
        self.assertRedirects(r, reverse("outlets:floor", args=[self.restaurant.pk]), fetch_redirect_response=False)
        order.refresh_from_db()
        self.assertFalse(order.is_open)

    def test_changes_need_post(self):
        order = self.open_order()
        for name in ("add_item", "settle", "send", "cancel", "discount", "move", "print_bill"):
            self.assertEqual(self.client.get(reverse(f"outlets:{name}", args=[order.pk])).status_code, 405, name)


class PaymentTests(TillTestCase):
    def test_cash_with_change(self):
        order = self.open_order()
        self.add(order, self.dish)
        r = self.settle(order, how="cash", tendered="20", remaining="11.00")
        self.assertRedirects(r, reverse("outlets:receipt", args=[order.pk]), fetch_redirect_response=False)
        order.refresh_from_db()
        self.assertFalse(order.is_open)
        p = order.payments.get()
        self.assertEqual((p.amount, p.tendered, p.change), (Decimal("11.00"), Decimal("20"), Decimal("9.00")))
        self.assertContains(self.client.get(r["Location"]), "9.00")

    def test_double_tap_does_not_take_the_money_twice(self):
        order = self.open_order()
        self.add(order, self.dish)
        self.add(order, self.wine)
        self.settle(order, how="card", amount="5.50", remaining="15.50")
        r = self.settle(order, how="card", amount="5.50", remaining="15.50", follow=True)
        self.assertEqual(order.payments.count(), 1)
        self.assertContains(r, "just updated")

    def test_split_bill_in_two_payments(self):
        order = self.open_order()
        self.add(order, self.dish)
        r = self.settle(order, how="card", amount="6.00")
        self.assertRedirects(r, reverse("outlets:order", args=[order.pk]), fetch_redirect_response=False)
        self.settle(order, how="cash", tendered="5.00")
        order.refresh_from_db()
        self.assertFalse(order.is_open)
        self.assertEqual(sum(p.amount for p in order.payments.all()), Decimal("11.00"))

    def test_cash_tip_from_the_change(self):
        order = self.open_order()
        self.add(order, self.dish)
        self.settle(order, how="cash", tendered="12", keep_change="1")
        p = order.payments.get()
        self.assertEqual(p.tip, Decimal("1"))

    def test_bad_amount_and_no_method_are_refused(self):
        order = self.open_order()
        self.add(order, self.dish)
        r = self.settle(order, how="cash", tendered="lots", follow=True)
        self.assertContains(r, "valid amount")
        r = self.settle(order, how="", follow=True)
        self.assertContains(r, "how the bill is settled")
        order.refresh_from_db()
        self.assertTrue(order.is_open)

    def test_charge_to_a_guest_in_the_hotel(self):
        res = self.make_reservation(status="checked_in")
        order = self.open_order()
        self.add(order, self.dish)
        self.settle(order, how="room", reservation=res.pk)
        order.refresh_from_db()
        self.assertFalse(order.is_open)
        self.assertTrue(res.folio.charges.filter(amount=Decimal("11.00")).exists())

    def test_unknown_customer_account(self):
        order = self.open_order()
        self.add(order, self.dish)
        r = self.settle(order, how="account", account_name="Nobody", follow=True)
        self.assertContains(r, "Nobody")
        order.refresh_from_db()
        self.assertTrue(order.is_open)


class ManagerTests(TillTestCase):
    def paid_order(self):
        order = self.open_order()
        self.add(order, self.dish)
        self.settle(order, how="cash", tendered="11")
        order.refresh_from_db()
        return order

    def test_discount_within_and_over_the_waiters_limit(self):
        order = self.open_order()
        self.add(order, self.dish)
        self.client.post(reverse("outlets:discount", args=[order.pk]), {"kind": "percent", "value": "100", "reason": "x"})
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal("11.00"))  # a waiter can't give 100% off
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("outlets:discount", args=[order.pk]), {"kind": "amount", "value": "1", "reason": "Regular"})
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal("10.00"))

    def test_only_a_manager_voids_a_receipt(self):
        order = self.paid_order()
        self.client.post(reverse("outlets:void_receipt", args=[order.pk]), {"reason": "Mistake"})
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.post(reverse("outlets:void_receipt", args=[order.pk]), {"reason": "Wrong table"})
        self.assertRedirects(r, reverse("outlets:receipt", args=[order.pk]), fetch_redirect_response=False)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertTrue(order.payments.get().voided)

    def test_void_a_part_payment(self):
        order = self.open_order()
        self.add(order, self.dish)
        self.settle(order, how="card", amount="5")
        p = order.payments.get()
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("outlets:void_payment", args=[order.pk, p.pk]), {"reason": "Wrong card"})
        p.refresh_from_db()
        self.assertTrue(p.voided)
        order.refresh_from_db()
        self.assertEqual(order.remaining, Decimal("11.00"))

    def test_receipts_list_and_bill_print_without_a_printer(self):
        order = self.paid_order()
        self.client.login(username="boss", password=PASSWORD)
        self.assertContains(self.client.get(reverse("outlets:receipts")), order.receipt_number)
        r = self.client.post(reverse("outlets:print_bill", args=[order.pk]), {"lang": "en"})
        self.assertEqual(r["Location"], reverse("outlets:receipt", args=[order.pk]) + "?print=1&lang=en")

    def test_other_staff_cannot_use_the_till(self):
        order = self.open_order()
        self.client.login(username="cleaner", password=PASSWORD)
        self.assertIn(self.client.get(reverse("outlets:order", args=[order.pk])).status_code, (302, 403))
        self.assertIn(self.settle(order, how="cash", tendered="20").status_code, (302, 403))
        self.assertEqual(Payment.objects.count(), 0)
