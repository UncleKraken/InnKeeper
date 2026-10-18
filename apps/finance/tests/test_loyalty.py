from decimal import Decimal as D

from django.urls import reverse

from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance import loyalty
from apps.finance.models import GiftVoucher, LoyaltyCard, Payment
from apps.finance.reports import day_summary
from apps.outlets import services as pos


class VoucherTests(HotelTestCase):
    def setUp(self):
        HotelSettings.objects.update(vouchers_enabled=True, voucher_months=12)
        clear_settings_cache()

    def _order(self, qty=1):
        o = pos.open_order(self.restaurant, user=self.waiter, table=self.table)
        pos.add_item(o, self.dish, user=self.waiter, quantity=qty)  # 11.00 each
        return o

    def test_sell_then_spend_in_two_visits(self):
        v = loyalty.sell_voucher(amount=D("30"), method="cash", user=self.waiter, buyer="Ana")
        self.assertRegex(v.code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertIsNotNone(v.expires_on)
        s = day_summary(self.today)
        self.assertEqual((s["cash"], s["revenue"], s["vouchers_sold"]), (D("30"), D("0"), D("30")))
        o1 = self._order(2)  # 22.00
        pos.pay_order(o1, method="voucher", user=self.waiter, voucher_code=v.code.lower().replace("-", " "))
        o1.refresh_from_db()
        self.assertEqual(o1.status, "closed")
        self.assertEqual(v.balance, D("8.00"))
        o2 = self._order(1)  # 11.00, voucher covers 8, the rest cash
        pos.pay_order(o2, method="voucher", user=self.waiter, voucher_code=v.code)
        o2.refresh_from_db()
        self.assertEqual((o2.status, o2.remaining, v.balance), ("open", D("3.00"), D("0")))
        with self.assertRaises(BusinessError):
            pos.pay_order(o2, method="voucher", user=self.waiter, voucher_code=v.code)
        pos.pay_order(o2, method="cash", user=self.waiter)
        s = day_summary(self.today)
        self.assertEqual((s["cash"], s["vouchers_spent"], s["revenue"]), (D("33.00"), D("30.00"), D("33.00")))
        self.assertEqual(s["received"], D("33.00"))  # voucher spending is not money

    def test_fiscal_payment_type(self):
        from apps.fiscal.services import _payments

        kind, rows = _payments([("voucher", D("10")), ("cash", D("5"))], D("15"))
        self.assertEqual(kind, "CASH")
        self.assertIn({"type": "SVOUCHER", "amount": "10.00"}, rows)

    def test_expired_voided_and_unknown(self):
        v = loyalty.sell_voucher(amount=D("10"), method="card", user=self.waiter)
        GiftVoucher.objects.filter(pk=v.pk).update(expires_on=self.today.replace(year=self.today.year - 1))
        o = self._order()
        with self.assertRaises(BusinessError):
            pos.pay_order(o, method="voucher", user=self.waiter, voucher_code=v.code)
        with self.assertRaises(BusinessError):
            pos.pay_order(o, method="voucher", user=self.waiter, voucher_code="NOPE-NOPE")
        v2 = loyalty.sell_voucher(amount=D("10"), method="cash", user=self.waiter)
        with self.assertRaises(BusinessError):
            loyalty.void_voucher(v2, user=self.waiter, reason="x")
        loyalty.void_voucher(v2, user=self.manager, reason="sold by mistake")
        self.assertTrue(Payment.objects.get(voucher=v2).voided)
        with self.assertRaises(BusinessError):
            pos.pay_order(o, method="voucher", user=self.waiter, voucher_code=v2.code)

    def test_voided_receipt_gives_the_value_back(self):
        v = loyalty.sell_voucher(amount=D("20"), method="cash", user=self.waiter)
        o = self._order()
        pos.pay_order(o, method="voucher", user=self.waiter, voucher_code=v.code)
        pos.void_receipt(o, user=self.manager, reason="wrong table")
        self.assertEqual(v.balance, D("20"))

    def test_pages_and_till(self):
        self.client.login(username="waiter", password=PASSWORD)
        r = self.client.post(reverse("outlets:vouchers"), {"amount": "25", "method": "card", "buyer": "Ben", "note": ""})
        v = GiftVoucher.objects.get()
        self.assertRedirects(r, reverse("outlets:voucher", args=[v.pk]))
        self.assertContains(self.client.get(r["Location"]), v.code)
        self.assertRedirects(self.client.get(reverse("outlets:vouchers") + "?q=" + v.code.lower()), reverse("outlets:voucher", args=[v.pk]))
        o = self._order()
        self.assertContains(self.client.get(reverse("outlets:order", args=[o.pk])), 'data-pane="voucher"')
        self.client.post(reverse("outlets:settle", args=[o.pk]), {"how": "voucher", "voucher_code": v.code, "remaining": "11.00"})
        o.refresh_from_db()
        self.assertEqual(o.status, "closed")


class LoyaltyTests(HotelTestCase):
    def setUp(self):
        HotelSettings.objects.update(loyalty_enabled=True, loyalty_stamps=3)
        clear_settings_cache()
        self.dish.earns_stamp = True
        self.dish.save()
        self.card = loyalty.create_card(name="Ana", phone="+355 69 123 4567")

    def _sale(self, qty, reward=False, pay=True):
        o = pos.open_order(self.restaurant, user=self.waiter, label="Bar")
        pos.add_item(o, self.dish, user=self.waiter, quantity=qty)
        pos.add_item(o, self.wine, user=self.waiter)  # doesn't earn
        loyalty.attach_card(o, self.card, self.waiter)
        if reward:
            loyalty.give_reward(o, self.waiter)
        if pay:
            pos.pay_order(o, method="cash", user=self.waiter)
        o.refresh_from_db()
        self.card.refresh_from_db()
        return o

    def test_find_by_phone_or_number(self):
        self.assertEqual(loyalty.find_card("0691234567"), self.card)
        self.assertEqual(loyalty.find_card(self.card.number), self.card)
        self.assertIsNone(loyalty.find_card("12"))

    def test_stamps_reward_and_void(self):
        self._sale(2)
        self.assertEqual(self.card.stamps, 2)
        with self.assertRaises(BusinessError):
            self._sale(1, reward=True, pay=False)  # only 2 of 3
        o = self._sale(2)
        self.assertEqual(self.card.stamps, 4)
        o2 = self._sale(1, reward=True)
        self.assertEqual((o2.discount, o2.total), (D("11.00"), D("4.50")))
        self.assertEqual((self.card.stamps, self.card.rewards), (1, 1))  # 4 − 3, the free one earns nothing
        pos.void_receipt(o, user=self.manager, reason="mistake")
        self.card.refresh_from_db()
        self.assertEqual(self.card.stamps, 0)

    def test_till_flow(self):
        self.client.login(username="waiter", password=PASSWORD)
        o = pos.open_order(self.restaurant, user=self.waiter, table=self.table)
        pos.add_item(o, self.dish, user=self.waiter)
        page = self.client.get(reverse("outlets:order", args=[o.pk]))
        self.assertContains(page, reverse("outlets:attach_card", args=[o.pk]))
        self.client.post(reverse("outlets:attach_card", args=[o.pk]), {"q": "069 123 4567"})
        o.refresh_from_db()
        self.assertEqual(o.loyalty_card, self.card)
        self.client.post(reverse("outlets:attach_card", args=[o.pk]), {"name": "Ben", "phone": ""})
        o.refresh_from_db()
        self.assertEqual(o.loyalty_card.name, "Ben")
        self.assertEqual(LoyaltyCard.objects.count(), 2)
        for url in (reverse("outlets:cards"), reverse("outlets:card", args=[self.card.pk])):
            self.assertEqual(self.client.get(url).status_code, 200)
        self.client.login(username="boss", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("core:settings") + "?tab=loyalty").status_code, 200)
