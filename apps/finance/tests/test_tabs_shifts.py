from decimal import Decimal

from django.urls import reverse

from apps.core.exceptions import BusinessError
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance import tabs
from apps.finance.models import Charge, CustomerAccount, Payment
from apps.finance.reports import day_summary
from apps.outlets import services as pos
from apps.outlets.models import Order

D = Decimal


class AccountTests(HotelTestCase):
    def setUp(self):
        self.account = CustomerAccount.objects.create(name="Agron", credit_limit=D("50"), opening_balance=D("10"))

    def order(self, qty=1):
        o = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(o, self.dish, user=self.waiter, quantity=qty)  # 11.00 each
        return o

    def test_bill_on_account_then_paid_later(self):
        o = pos.charge_to_account(self.order(2), self.account, user=self.waiter)
        o.refresh_from_db()
        self.assertEqual((o.status, o.settlement), (Order.Status.CLOSED, Order.Settlement.ACCOUNT))
        self.assertEqual(self.account.balance, D("32.00"))  # 10 from before + 22
        s = day_summary(self.today)
        self.assertEqual((s["revenue"], s["received"], s["on_account"]), (D("22.00"), D("0"), D("22.00")))
        tabs.pay_account(self.account, amount=D("20"), method="cash", user=self.waiter)
        self.assertEqual(self.account.balance, D("12.00"))
        s = day_summary(self.today)
        self.assertEqual((s["cash"], s["account_payments"]), (D("20.00"), D("20.00")))
        rows = tabs.statement(self.account)
        self.assertEqual([r["balance"] for r in rows], [D("32.00"), D("12.00")])

    def test_credit_limit(self):
        with self.assertRaises(BusinessError):
            pos.charge_to_account(self.order(4), self.account, user=self.waiter)  # 10 + 44 > 50
        pos.charge_to_account(self.order(4), self.account, user=self.manager)  # a manager may allow it

    def test_part_paid_rest_on_account(self):
        o = self.order(2)
        pos.pay_order(o, method="cash", user=self.waiter, amount=D("2"))
        pos.charge_to_account(o, self.account, user=self.waiter)
        self.assertEqual(self.account.balance, D("30.00"))
        self.assertEqual(sum(c.amount for c in Charge.objects.filter(order=o, voided=False)), D("22.00"))

    def test_void_takes_it_off_the_account(self):
        o = pos.charge_to_account(self.order(), self.account, user=self.waiter)
        pos.void_receipt(o, user=self.manager, reason="wrong customer")
        self.assertEqual(self.account.balance, D("10.00"))

    def test_closed_accounts_and_refunds(self):
        with self.assertRaises(BusinessError):
            tabs.pay_account(self.account, amount=D("-5"), method="cash", user=self.waiter)
        self.account.is_active = False
        self.account.save()
        with self.assertRaises(BusinessError):
            pos.charge_to_account(self.order(), self.account, user=self.waiter)

    def test_from_the_till(self):
        o = self.order()
        self.client.login(username="waiter", password=PASSWORD)
        page = self.client.get(reverse("outlets:order", args=[o.pk]))
        self.assertContains(page, 'data-pane="account"')
        self.client.post(reverse("outlets:settle", args=[o.pk]), {"how": "account", "account_name": "agr", "remaining": "11.00"})
        o.refresh_from_db()
        self.assertEqual(o.settlement, Order.Settlement.ACCOUNT)

    def test_pages_and_permissions(self):
        self.client.login(username="waiter", password=PASSWORD)
        self.assertContains(self.client.get(reverse("finance:accounts")), "Agron")
        self.assertEqual(self.client.get(reverse("finance:account_create")).status_code, 403)
        self.client.post(reverse("finance:account_pay", args=[self.account.pk]), {"amount": "5", "method": "cash"})
        self.assertEqual(self.account.balance, D("5.00"))
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.post(reverse("finance:account_create"), {"name": "Besa", "phone": "", "opening_balance": "0", "is_active": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertContains(self.client.get(r["Location"]), "Besa")
        self.client.login(username="cleaner", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("finance:accounts")).status_code, 403)


class ShiftAndTipTests(HotelTestCase):
    def order(self):
        o = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(o, self.dish, user=self.waiter)  # 11.00
        return o

    def test_shift_counts_the_cash_to_hand_in(self):
        shift = tabs.start_shift(self.waiter, D("20"))
        with self.assertRaises(BusinessError):
            tabs.start_shift(self.waiter)
        pos.pay_order(self.order(), method="cash", user=self.waiter, tendered=D("15"), tip=D("4"))
        pos.pay_order(self.order(), method="card", user=self.waiter, tip=D("2"))
        pos.pay_order(self.order(), method="cash", user=self.manager)  # someone else's money
        s = tabs.summary(shift)
        self.assertEqual((s["cash"], s["tips_cash"], s["tips_card"]), (D("11.00"), D("4.00"), D("2.00")))
        self.assertEqual(s["expected_cash"], D("29.00"))  # 20 + 11 − 2 card tip paid out
        tabs.end_shift(shift, counted=D("28"), user=self.waiter)
        shift.refresh_from_db()
        self.assertEqual(shift.difference, D("-1.00"))
        with self.assertRaises(BusinessError):
            tabs.end_shift(shift, counted=D("28"), user=self.waiter)

    def test_tip_is_not_revenue_and_not_change(self):
        o = self.order()
        p = pos.pay_order(o, method="cash", user=self.waiter, tendered=D("15"), tip=D("4"))
        self.assertEqual((p.amount, p.change), (D("11.00"), D("0")))
        with self.assertRaises(BusinessError):
            pos.pay_order(self.order(), method="cash", user=self.waiter, tendered=D("12"), tip=D("4"))
        s = day_summary(self.today)
        self.assertEqual((s["revenue"], s["cash"], s["tips_cash"]), (D("11.00"), D("11.00"), D("4.00")))

    def test_card_tips_come_out_of_the_drawer_at_day_close(self):
        pos.pay_order(self.order(), method="card", user=self.waiter, tip=D("3"))
        pos.pay_order(self.order(), method="cash", user=self.waiter)
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.get(reverse("finance:day_close"))
        self.assertEqual(r.context["expected_now"], D("8.00"))  # 11 cash − 3 card tip

    def test_keep_the_change_from_the_till(self):
        o = self.order()
        self.client.login(username="waiter", password=PASSWORD)
        self.client.post(
            reverse("outlets:settle", args=[o.pk]),
            {"how": "cash", "amount": "11.00", "tendered": "20", "keep_change": "1", "remaining": "11.00"},
        )
        self.assertEqual(Payment.objects.get(order=o).tip, D("9.00"))

    def test_pages(self):
        self.client.login(username="waiter", password=PASSWORD)
        self.client.post(reverse("finance:shift_start"), {"opening_float": "10"})
        page = self.client.get(reverse("finance:my_shift"))
        shift = page.context["shift"]
        self.assertIsNotNone(shift)
        r = self.client.post(reverse("finance:shift_end", args=[shift.pk]), {"counted": "10"})
        self.assertRedirects(r, reverse("finance:shift_report", args=[shift.pk]))
        self.assertContains(self.client.get(r["Location"]), "10.00")
        self.client.login(username="money", password=PASSWORD)
        self.assertContains(self.client.get(reverse("finance:shifts")), "waiter")
