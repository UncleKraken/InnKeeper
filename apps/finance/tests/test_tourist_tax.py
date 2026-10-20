from decimal import Decimal as D

from django.urls import reverse
from django.utils import timezone

from apps.core.models import HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance import monthly, reports, tourist_tax
from apps.finance.models import Charge, Folio
from apps.frontdesk import services
from apps.frontdesk.models import Reservation


class TouristTaxTests(HotelTestCase):
    def setUp(self):
        hs = HotelSettings.load()
        hs.tourist_tax_enabled = True
        hs.tourist_tax_amount = D("1.40")
        hs.save()

    def stay(self, nights=3, children=0):
        res = self.make_reservation(start=-nights, nights=nights, status=Reservation.Status.CHECKED_IN)
        Reservation.objects.filter(pk=res.pk).update(children=children)
        res.refresh_from_db()
        Folio.objects.get_or_create(reservation=res)
        return res

    def taxes(self, res):
        return Charge.objects.filter(reservation=res, kind=Charge.Kind.TOURIST_TAX)

    def test_posted_with_the_nights_per_guest(self):
        res = self.stay(nights=3, children=1)
        services.post_accommodation(res, self.reception, self.today)
        tax = self.taxes(res).get()
        self.assertEqual(tax.quantity, 6)  # 2 adults × 3 nights, children exempt
        self.assertEqual(tax.amount, D("8.40"))
        self.assertEqual(tax.folio, res.folio)
        services.post_accommodation(res, self.reception, self.today)  # nothing new to post
        self.assertEqual(self.taxes(res).count(), 1)

    def test_night_audit_posts_each_night(self):
        res = self.stay(nights=2)
        services.night_audit(self.today)
        self.assertEqual([t.quantity for t in self.taxes(res).order_by("business_date")], [2, 2])

    def test_per_room_children_and_max_nights(self):
        hs = HotelSettings.load()
        hs.tourist_tax_basis = HotelSettings.TouristTaxBasis.ROOM
        hs.tourist_tax_max_nights = 2
        hs.save()
        res = self.stay(nights=4, children=1)
        services.post_accommodation(res, self.reception, self.today)
        self.assertEqual(self.taxes(res).get().quantity, 2)
        hs.tourist_tax_basis = HotelSettings.TouristTaxBasis.GUEST
        hs.tourist_tax_children = True
        hs.tourist_tax_max_nights = 0
        hs.save()
        res2 = self.make_reservation(room=self.room2, start=-1, nights=1, status=Reservation.Status.CHECKED_IN)
        Reservation.objects.filter(pk=res2.pk).update(children=1)
        res2.refresh_from_db()
        services.post_accommodation(res2, self.reception, self.today)
        self.assertEqual(self.taxes(res2).get().quantity, 3)

    def test_off_means_nothing(self):
        hs = HotelSettings.load()
        hs.tourist_tax_enabled = False
        hs.save()
        res = self.stay()
        services.post_accommodation(res, self.reception, self.today)
        self.assertFalse(self.taxes(res).exists())

    def test_not_in_sales_vat_or_fiscal(self):
        res = self.stay(nights=1)
        services.post_accommodation(res, self.reception, self.today)
        day = reports.day_summary(self.today)
        self.assertEqual(day["revenue"], D("80.00"))
        self.assertEqual(day["tourist_tax"], D("2.80"))
        m = monthly.report(self.today.replace(day=1), self.today)
        self.assertEqual(m["revenue"], D("80.00"))
        self.assertEqual(m["tourist_tax"], D("2.80"))
        self.assertEqual(res.folio.balance, D("82.80"))  # the guest pays it
        self.assertFalse(Charge.objects.filter(kind=Charge.Kind.TOURIST_TAX).revenue().exists())

    def test_month_list_and_excel(self):
        res = self.stay(nights=2)
        services.post_accommodation(res, self.reception, self.today)
        data = tourist_tax.report(self.today.replace(day=1), self.today)
        self.assertEqual(data["total"], D("5.60"))
        self.assertEqual(data["units"], 4)
        self.assertEqual(data["due"].day, 5)
        self.client.login(username="money", password=PASSWORD)
        r = self.client.get(reverse("finance:tourist_tax") + f"?month={self.today:%Y-%m}")
        self.assertContains(r, "Ana Koci")
        r = self.client.get(reverse("finance:tourist_tax") + f"?month={self.today:%Y-%m}&format=xlsx")
        self.assertEqual(r.status_code, 200)

    def test_void_counts_on_the_list(self):
        res = self.stay(nights=1)
        services.post_accommodation(res, self.reception, self.today)
        self.taxes(res).update(voided=True, voided_at=timezone.now())
        self.assertEqual(tourist_tax.report(self.today.replace(day=1), self.today)["total"], D("0"))

    def test_due_date(self):
        from datetime import date

        self.assertEqual(tourist_tax.due_date(date(2026, 12, 1)), date(2027, 1, 5))
        self.assertEqual(tourist_tax.due_date(date(2026, 2, 1)), date(2026, 3, 5))

    def test_settings_tab(self):
        self.client.login(username="boss", password=PASSWORD)
        self.assertContains(self.client.get(reverse("core:settings") + "?tab=tourist_tax"), "tourist_tax_amount")
        r = self.client.post(
            reverse("core:settings") + "?tab=tourist_tax",
            {"tourist_tax_enabled": "on", "tourist_tax_amount": "", "tourist_tax_basis": "guest", "tourist_tax_max_nights": "0"},
        )
        self.assertEqual(r.status_code, 200)  # the amount is required when it is on
        r = self.client.post(
            reverse("core:settings") + "?tab=tourist_tax",
            {"tourist_tax_enabled": "on", "tourist_tax_amount": "140", "tourist_tax_basis": "room", "tourist_tax_max_nights": "0"},
        )
        self.assertEqual(r.status_code, 302)
        from apps.core.models import clear_settings_cache

        clear_settings_cache()
        self.assertEqual(HotelSettings.load().tourist_tax_basis, "room")

    def test_home_page_reminds_early_in_the_month(self):
        from datetime import date
        from unittest import mock

        res = self.stay(nights=1)
        services.post_accommodation(res, self.reception, self.today)
        Charge.objects.filter(kind=Charge.Kind.TOURIST_TAX).update(business_date=date(2026, 9, 20))
        self.client.login(username="boss", password=PASSWORD)
        with mock.patch("apps.core.businessday.business_date", return_value=date(2026, 10, 3)):
            r = self.client.get("/")
        self.assertContains(r, "month=2026-09")

    def test_expected_at_check_out_includes_the_tax_so_check_out_works(self):
        res = self.stay(nights=2)
        self.client.login(username="desk", password=PASSWORD)
        r = self.client.get(reverse("frontdesk:reservation_detail", args=[res.pk]))
        self.assertEqual(r.context["pending_tax"], D("5.60"))
        expected = r.context["expected_balance"]
        self.assertEqual(expected, D("165.60"))
        services.add_payment(res.folio, amount=expected, method="cash", user=self.reception)
        services.check_out(res, self.reception)  # no "still owes" error
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.CHECKED_OUT)


class FinanceRoleLinksTests(HotelTestCase):
    def test_accountant_sees_receipts_but_no_dead_links(self):
        from apps.finance.models import Payment
        from apps.outlets import services as pos

        order = pos.open_order(self.restaurant, user=self.waiter, table=self.table)
        pos.add_item(order, self.dish, user=self.waiter)
        pos.pay_order(order, method=Payment.Method.CASH, user=self.waiter)
        res = self.make_reservation(start=-1, nights=1, status=Reservation.Status.CHECKED_IN)
        services.post_accommodation(res, self.reception, self.today)
        self.client.login(username="money", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("outlets:receipt", args=[order.pk])).status_code, 200)
        ledger = self.client.get(reverse("finance:ledger")).content.decode()
        self.assertNotIn(reverse("frontdesk:reservation_detail", args=[res.pk]), ledger)
        self.assertNotIn("void_receipt", self.client.get(reverse("outlets:receipt", args=[order.pk])).content.decode())
