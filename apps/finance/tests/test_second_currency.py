from decimal import Decimal as D

from django.urls import reverse

from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance import reports, tabs
from apps.finance.models import DayClose, Payment
from apps.frontdesk import services as fd
from apps.frontdesk.models import Reservation
from apps.outlets import services as pos


class SecondCurrencyTests(HotelTestCase):
    """Prices in euros; the guest may also pay cash in lekë (1 L = 0.01 €)."""

    def setUp(self):
        hs = HotelSettings.load()
        hs.second_currency, hs.second_currency_symbol, hs.second_currency_rate = "ALL", "L", D("0.0100")
        hs.save()
        clear_settings_cache()

    def order(self):
        o = pos.open_order(self.restaurant, user=self.waiter, table=self.table)
        pos.add_item(o, self.dish, user=self.waiter)  # 11.00 €
        return o

    def test_till_takes_lek_and_gives_change_in_euros(self):
        o = self.order()
        self.client.login(username="waiter", password=PASSWORD)
        r = self.client.post(reverse("outlets:settle", args=[o.pk]), {"how": "cash", "tendered": "1200", "tender_currency": "ALL"}, follow=True)
        p = Payment.objects.get(order=o)
        self.assertEqual((p.amount, p.tendered, p.change), (D("11.00"), D("12.00"), D("1.00")))
        self.assertEqual((p.foreign_currency, p.foreign_amount, p.foreign_rate), ("ALL", D("1200.00"), D("0.0100")))
        self.assertTrue(any("1.00" in str(m) for m in r.context["messages"]))

    def test_too_little_and_unknown_currency_are_refused(self):
        o = self.order()
        self.client.login(username="waiter", password=PASSWORD)
        self.client.post(reverse("outlets:settle", args=[o.pk]), {"how": "cash", "tendered": "1000", "tender_currency": "ALL"})
        self.client.post(reverse("outlets:settle", args=[o.pk]), {"how": "cash", "tendered": "20", "tender_currency": "USD"})
        self.assertFalse(Payment.objects.exists())

    def test_keep_change_as_tip(self):
        o = self.order()
        self.client.login(username="waiter", password=PASSWORD)
        self.client.post(reverse("outlets:settle", args=[o.pk]), {"how": "cash", "tendered": "1200", "tender_currency": "ALL", "keep_change": "1"})
        p = Payment.objects.get(order=o)
        self.assertEqual((p.tip, p.change), (D("1.00"), D("0.00")))

    def test_day_close_counts_both_drawers(self):
        o = self.order()
        pos.pay_order(o, method="cash", user=self.waiter, foreign={"tendered": D("12.00"), "foreign_currency": "ALL", "foreign_amount": D("1200.00"), "foreign_rate": D("0.0100")})
        o2 = pos.open_order(self.restaurant, user=self.waiter, table=self.table)
        pos.add_item(o2, self.wine, user=self.waiter)  # 4.50 € in euros
        pos.pay_order(o2, method="cash", user=self.waiter, tendered=D("5.00"))
        s = reports.day_summary(self.today)
        self.assertEqual(s["cash"], D("15.50"))
        self.assertEqual((s["foreign_code"], s["foreign_received"], s["foreign_value"]), ("ALL", D("1200.00"), D("12.00")))
        # Euro drawer: 4.50 in, 1.00 change out for the lek payment → 3.50 more than at the start.
        self.client.login(username="money", password=PASSWORD)
        self.client.post(reverse("finance:day_close") + f"?date={self.today}", {
            "opening_float": "50", "counted_cash": "53.50", "opening_second": "0", "counted_second": "1200", "notes": "",
        })
        z = DayClose.objects.get()
        self.assertEqual((z.expected_cash, z.difference), (D("53.50"), D("0.00")))
        self.assertEqual((z.second_currency, z.expected_second, z.difference_second), ("ALL", D("1200.00"), D("0.00")))
        self.assertContains(self.client.get(reverse("finance:day_close") + f"?date={self.today}"), "1200.00")

    def test_shift_hand_in(self):
        shift = tabs.start_shift(self.waiter, opening_float=D("20"))
        o = self.order()
        self.client.login(username="waiter", password=PASSWORD)
        self.client.post(reverse("outlets:settle", args=[o.pk]), {"how": "cash", "tendered": "1500", "tender_currency": "ALL"})
        s = tabs.summary(shift)
        self.assertEqual((s["expected_cash"], s["foreign_received"]), (D("16.00"), D("1500.00")))  # 20 − 4.00 change
        tabs.end_shift(shift, counted=D("16"), counted_second=D("1500"), user=self.waiter)
        shift.refresh_from_db()
        self.assertEqual((shift.expected_second, shift.counted_second), (D("1500.00"), D("1500.00")))

    def test_reception_takes_lek_on_a_room_bill(self):
        res = self.make_reservation(start=-1, nights=1, status=Reservation.Status.CHECKED_IN)
        p = fd.add_payment(res.folio, amount=D("80.00"), method="cash", user=self.reception, foreign_amount=D("8500"))
        self.assertEqual((p.tendered, p.change, p.foreign_currency), (D("85.00"), D("5.00"), "ALL"))
        self.client.login(username="desk", password=PASSWORD)
        self.assertContains(self.client.get(reverse("frontdesk:reservation_detail", args=[res.pk])), "8500.00 ALL")

    def test_settings_validate_the_rate(self):
        self.client.login(username="boss", password=PASSWORD)
        hs = HotelSettings.load()
        data = {"name": hs.name, "tax_status": hs.tax_status, "currency": "EUR", "currency_symbol": "€", "vat_rate": "20",
                "default_language": "sq", "day_ends_at": "0", "check_in_time": "14:00", "check_out_time": "11:00",
                "second_currency": "eur", "second_currency_rate": ""}
        r = self.client.post(reverse("core:settings") + "?tab=business", data)
        self.assertEqual(r.status_code, 200)  # same as the main currency, and no rate
        data.update(second_currency="usd", second_currency_rate="0.92")
        r = self.client.post(reverse("core:settings") + "?tab=business", data)
        self.assertEqual(r.status_code, 302)
        clear_settings_cache()
        hs = HotelSettings.load()
        self.assertEqual((hs.second_currency, hs.second_currency_symbol), ("USD", "$"))

    def test_receipts_show_what_was_handed_over(self):
        from apps.outlets.models import Printer
        from apps.outlets.printing import receipt_document

        o = self.order()
        pos.pay_order(o, method="cash", user=self.waiter, foreign={"tendered": D("12.00"), "foreign_currency": "ALL", "foreign_amount": D("1200.00"), "foreign_rate": D("0.0100")})
        o.refresh_from_db()
        data = receipt_document(o, Printer(name="Bar", connection="network", address="127.0.0.1"))
        self.assertIn(b"1200.00 ALL", data)
        self.assertIn(b"0.01", data)
        self.client.login(username="waiter", password=PASSWORD)
        self.assertContains(self.client.get(reverse("outlets:receipt", args=[o.pk])), "1200.00 ALL")


class WholeUnitTests(HotelTestCase):
    def test_lek_due_is_rounded_up_to_a_whole_lek(self):
        from decimal import Decimal as D

        from apps.finance.currency import due_in_second

        self.assertEqual(due_in_second(D("4.40"), D("0.0104"), "ALL"), D("424.00"))
        self.assertEqual(due_in_second(D("4.40"), D("0.0104"), "EUR"), D("423.08"))
        self.assertEqual(due_in_second(D("1000"), D("100"), "EUR"), D("10.00"))


class UnclosedDayTests(HotelTestCase):
    def test_day_close_points_to_yesterday_when_it_was_not_closed(self):
        from datetime import timedelta

        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter)
        pos.pay_order(order, method="cash", user=self.waiter)
        Payment.objects.filter(order=order).update(business_date=self.today - timedelta(days=1))
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.get(reverse("finance:day_close"))
        self.assertContains(r, "alert alert-warning no-print")
        self.assertContains(r, f"?date={(self.today - timedelta(days=1)).isoformat()}")
        z = D("0")
        DayClose.objects.create(
            business_date=self.today - timedelta(days=1), opening_float=z, cash_sales=z, cash_expenses=z, expected_cash=z,
            counted_cash=z, card_total=z, other_total=z, revenue_total=z,
        )
        r = self.client.get(reverse("finance:day_close"))
        self.assertNotContains(r, "alert alert-warning no-print")


class WholeLekChangeTests(HotelTestCase):
    def test_exact_whole_lek_gives_no_cent_of_change(self):
        hs = HotelSettings.load()
        hs.currency, hs.second_currency, hs.second_currency_symbol, hs.second_currency_rate = "EUR", "ALL", "L", D("0.0104")
        hs.save()
        clear_settings_cache()
        from apps.finance.currency import foreign_payment

        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.wine, user=self.waiter, quantity=2)  # 9.00 €; 866 L = 9.0064 € → would be 0.01 change
        self.assertEqual(foreign_payment("ALL", D("866"))["tendered"], D("9.01"))
        pos.pay_order(order, method="cash", user=self.waiter, foreign=foreign_payment("ALL", D("866")))
        p = Payment.objects.get(order=order)
        self.assertEqual((p.tendered, p.change, p.foreign_amount), (D("9.00"), D("0"), D("866.00")))
        # A real overpayment still gives change.
        order2 = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order2, self.wine, user=self.waiter)
        pos.pay_order(order2, method="cash", user=self.waiter, foreign=foreign_payment("ALL", D("500")))
        self.assertEqual(Payment.objects.get(order=order2).change, D("0.70"))
