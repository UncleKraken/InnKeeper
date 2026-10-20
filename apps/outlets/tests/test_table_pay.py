from decimal import Decimal as D

from django.core.cache import cache
from django.urls import reverse

from apps.core.models import HotelSettings
from apps.core.testing import HotelTestCase
from apps.finance.models import Payment
from apps.outlets import services as pos
from apps.outlets.models import Order
from apps.payments import providers
from apps.payments.models import PaymentLink


class PayAtTableTests(HotelTestCase):
    def setUp(self):
        cache.clear()
        hs = HotelSettings.load()
        hs.payment_provider, hs.paysera_project_id, hs.paysera_password = "paysera", "12345", "secret-pass"
        hs.public_url = "https://hotel.example"
        hs.save()
        self.restaurant.qr_ordering = True
        self.restaurant.qr_payments = True
        self.restaurant.save()
        self.table.refresh_from_db()
        self.order = pos.open_order(self.restaurant, user=self.waiter, table=self.table)
        pos.add_item(self.order, self.dish, user=self.waiter, quantity=2)  # 22.00
        self.p = providers.Paysera("12345", "secret-pass", test=True)
        self.page = reverse("menu:table", args=[self.table.qr_token])

    def paid(self, link, amount=None):
        params = {"projectid": "12345", "orderid": link.token, "amount": str(amount or link.minor_units),
                  "currency": link.currency, "status": "1", "requestid": "987", "test": "1"}
        data = self.p.encode(params)
        return self.client.get(reverse("payments:paysera_callback"), {"data": data, "ss1": self.p.sign(data)})

    def test_guest_sees_the_bill_and_pays_with_a_tip(self):
        r = self.client.get(self.page + "?lang=en")
        self.assertContains(r, "Your bill")
        self.assertContains(r, "Pay by card")
        r = self.client.post(reverse("menu:table_pay", args=[self.table.qr_token]), {"tip": "10", "lang": "en"})
        self.assertTrue(r["Location"].startswith("https://bank.paysera.com/pay/"))
        link = PaymentLink.objects.get()
        self.assertEqual((link.amount, link.tip, link.order), (D("24.20"), D("2.20"), self.order))
        self.paid(link)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CLOSED)
        pay = self.order.payments.get()
        self.assertEqual((pay.amount, pay.tip, pay.method), (D("22.00"), D("2.20"), Payment.Method.ONLINE))
        link.refresh_from_db()
        self.assertEqual((link.status, link.error), ("paid", ""))
        self.assertNotContains(self.client.get(self.page), "Pay by card")  # nothing left to pay

    def test_pressing_pay_twice_reuses_the_link(self):
        url = reverse("menu:table_pay", args=[self.table.qr_token])
        self.client.post(url, {"tip": "0"})
        self.client.post(url, {"tip": "0"})
        self.assertEqual(PaymentLink.objects.filter(status="pending").count(), 1)
        self.client.post(url, {"tip": "5"})  # a different amount replaces it
        self.assertEqual(PaymentLink.objects.filter(status="pending").count(), 1)
        self.assertEqual(PaymentLink.objects.filter(status="cancelled").count(), 1)

    def test_bill_paid_in_cash_meanwhile_is_flagged_for_refund(self):
        self.client.post(reverse("menu:table_pay", args=[self.table.qr_token]), {"tip": "0"})
        link = PaymentLink.objects.get()
        pos.pay_order(self.order, method=Payment.Method.CASH, user=self.waiter, amount=D("10.00"))
        self.paid(link)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CLOSED)
        link.refresh_from_db()
        self.assertEqual(link.status, "paid")
        self.assertIn("10.00", link.error)  # 22 paid by card, only 12 was left
        self.assertTrue(Payment.objects.filter(order__isnull=True, amount=D("10.00"), method="online").exists())

    def test_off_without_switch_or_provider(self):
        self.restaurant.qr_payments = False
        self.restaurant.save()
        self.assertNotContains(self.client.get(self.page), "Pay by card")
        r = self.client.post(reverse("menu:table_pay", args=[self.table.qr_token]), {"tip": "0"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PaymentLink.objects.exists())

    def test_tip_shown_is_the_tip_charged(self):
        pos.change_quantity(self.order.lines.get(), -1, user=self.waiter)
        pos.add_item(self.order, self.wine, user=self.waiter)  # 11.00 + 4.50 = 15.50 → 5% = 0.775
        r = self.client.get(self.page)
        shown = dict(r.context["tips"])[5]
        self.client.post(reverse("menu:table_pay", args=[self.table.qr_token]), {"tip": "5"})
        self.assertEqual(PaymentLink.objects.get().tip, shown)
        self.assertEqual(shown, D("0.78"))
