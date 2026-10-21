from decimal import Decimal
from unittest import mock

from django.urls import reverse

from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Folio
from apps.fiscal import buyer, cis, services
from apps.frontdesk import services as fd
from apps.frontdesk.models import Reservation
from apps.outlets import services as pos
from apps.outlets.models import Printer
from apps.outlets.printing import receipt_document

from .test_fiscal import FakeCIS, configure

D = Decimal


class BuyerFormTests(HotelTestCase):
    def test_nuis_is_checked_and_uppercased(self):
        f = buyer.BuyerForm({"buyer_name": "Alfa sh.p.k.", "buyer_nuis": " l12345678a "})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["buyer_nuis"], "L12345678A")
        for bad in ("12345678", "L1234567A", "LL2345678A"):
            self.assertFalse(buyer.BuyerForm({"buyer_name": "X", "buyer_nuis": bad}).is_valid(), bad)

    def test_name_and_nuis_go_together(self):
        self.assertFalse(buyer.BuyerForm({"buyer_nuis": "L12345678A"}).is_valid())
        self.assertFalse(buyer.BuyerForm({"buyer_name": "Alfa"}).is_valid())
        self.assertTrue(buyer.BuyerForm({}).is_valid())


class BuyerFiscalTests(HotelTestCase):
    def setUp(self):
        configure()
        self.cis = FakeCIS()
        p = mock.patch.object(cis, "send", self.cis)
        p.start()
        self.addCleanup(p.stop)
        services._offline_until = None

    def _buyer_el(self):
        inv = self.cis.invoices()[-1].find(f"{{{cis.NS}}}Invoice")
        return inv.find(f"{{{cis.NS}}}Buyer")

    def test_restaurant_bill_to_a_company(self):
        self.client.login(username="waiter", password=PASSWORD)
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter)
        r = self.client.post(reverse("outlets:invoice_buyer", args=[order.pk]), {
            "buyer_name": "Alfa sh.p.k.", "buyer_nuis": "k91234567b", "buyer_town": "Tiranë",
        })
        self.assertEqual(r.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.buyer_nuis, "K91234567B")
        with self.captureOnCommitCallbacks(execute=True):
            pos.pay_order(order, method="card", user=self.waiter)
        b = self._buyer_el()
        self.assertEqual((b.get("IDType"), b.get("IDNum"), b.get("Name")), ("NUIS", "K91234567B", "Alfa sh.p.k."))
        self.assertEqual((b.get("Town"), b.get("Address"), b.get("Country")), ("Tiranë", "-", "ALB"))
        # Shown on the receipt (screen and thermal printer).
        r = self.client.get(reverse("outlets:receipt", args=[order.pk]))
        self.assertContains(r, "K91234567B")
        printed = receipt_document(order, Printer(name="t", paper_width=80))
        self.assertIn(b"K91234567B", printed)
        # The voided receipt's correction goes to the same company.
        with self.captureOnCommitCallbacks(execute=True):
            pos.void_receipt(order, user=self.manager, reason="wrong")
        self.assertEqual(self._buyer_el().get("IDNum"), "K91234567B")

    def test_private_customer_has_no_buyer(self):
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter)
        with self.captureOnCommitCallbacks(execute=True):
            pos.pay_order(order, method="cash", user=self.waiter)
        self.assertIsNone(self._buyer_el())

    def test_guest_bill_to_a_company_and_the_e_invoice_reminder(self):
        self.client.login(username="desk", password=PASSWORD)
        self.guest.company = "Beta Travel"
        self.guest.save()
        res = self.make_reservation(nights=1, status=Reservation.Status.CHECKED_IN)
        url = reverse("frontdesk:reservation_detail", args=[res.pk])
        self.assertContains(self.client.get(url), 'value="Beta Travel"')
        self.client.post(reverse("frontdesk:invoice_buyer", args=[res.pk]), {"buyer_name": "Beta Travel", "buyer_nuis": "12"})
        self.assertFalse(Folio.objects.get(reservation=res).buyer_nuis)
        self.client.post(reverse("frontdesk:invoice_buyer", args=[res.pk]), {
            "buyer_name": "Beta Travel", "buyer_nuis": "M01234567C", "buyer_address": "Rr. Durrësit 5",
        })
        folio = Folio.objects.get(reservation=res)
        self.assertEqual(folio.buyer_nuis, "M01234567C")
        fd.add_payment(folio, amount=D("80"), method="bank_transfer", user=self.reception)
        r = self.client.get(url)
        self.assertContains(r, "M01234567C")
        self.assertContains(r, "e-fatur")
        self.assertContains(self.client.get(reverse("frontdesk:invoice", args=[res.pk])), "M01234567C")
        with self.captureOnCommitCallbacks(execute=True):
            fd.check_out(res, self.reception)
        b = self._buyer_el()
        self.assertEqual((b.get("IDNum"), b.get("Address")), ("M01234567C", "Rr. Durrësit 5"))
        # Closed: it can't be changed any more.
        self.client.post(reverse("frontdesk:invoice_buyer", args=[res.pk]), {"clear": "1"})
        self.assertEqual(Folio.objects.get(reservation=res).buyer_nuis, "M01234567C")

    def test_clear_makes_it_out_to_the_guest(self):
        self.client.login(username="desk", password=PASSWORD)
        res = self.make_reservation(nights=1)
        url = reverse("frontdesk:invoice_buyer", args=[res.pk])
        self.client.post(url, {"buyer_name": "Gama", "buyer_nuis": "L12345678A"})
        self.client.post(url, {"clear": "1"})
        folio = Folio.objects.get(reservation=res)
        self.assertEqual((folio.buyer_name, folio.buyer_nuis), ("", ""))


class BuyerMistakeTests(HotelTestCase):
    def test_a_wrong_nuis_keeps_what_was_typed_and_shows_one_error_in_the_card(self):
        self.client.login(username="desk", password=PASSWORD)
        res = self.make_reservation(nights=1)
        self.client.post(reverse("frontdesk:invoice_buyer", args=[res.pk]), {"buyer_name": "Alfa Tours", "buyer_nuis": "12345"})
        r = self.client.get(reverse("frontdesk:reservation_detail", args=[res.pk]))
        self.assertContains(r, 'value="Alfa Tours"')
        self.assertContains(r, 'value="12345"')
        self.assertContains(r, 'id="buyer" open')
        self.assertContains(r, "L12345678A", count=1)
        self.assertNotContains(r, "Enter the company&#x27;s NUIS")
        # Only once: the next visit shows the saved state again.
        r = self.client.get(reverse("frontdesk:reservation_detail", args=[res.pk]))
        self.assertNotContains(r, 'value="12345"')

    def test_till_keeps_the_typed_values_and_reopens_the_pane(self):
        self.client.login(username="waiter", password=PASSWORD)
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter)
        self.client.post(reverse("outlets:invoice_buyer", args=[order.pk]), {"buyer_name": "Beta", "buyer_nuis": "x1"})
        r = self.client.get(reverse("outlets:order", args=[order.pk]))
        self.assertContains(r, 'data-open="more"')
        self.assertContains(r, 'value="x1"')
