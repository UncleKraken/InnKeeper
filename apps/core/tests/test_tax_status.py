from decimal import Decimal

from django.urls import reverse

from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.setup import SetupAnswers, apply_setup
from apps.core.testing import PASSWORD, HotelTestCase
from apps.frontdesk import services as fd
from apps.outlets import printing
from apps.outlets import services as pos
from apps.outlets.models import Printer


class TaxStatusTests(HotelTestCase):
    def status(self, value, **extra):
        hs = HotelSettings.load()
        hs.tax_id = "L12345678A"
        hs.vat_rate = Decimal("20")
        hs.fiscal_enabled = True
        hs.tax_status = value
        for k, v in extra.items():
            setattr(hs, k, v)
        hs.save()
        clear_settings_cache()
        return HotelSettings.load()

    def paid_order(self):
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter)
        pos.pay_order(order, method="cash", user=self.waiter)
        order.refresh_from_db()
        return order

    def test_registered_with_vat(self):
        hs = self.status("vat")
        self.assertTrue((hs.registered, hs.charges_vat, hs.fiscal_on))
        data = printing.receipt_document(self.paid_order(), Printer(name="p", paper_width=80))
        self.assertIn(b"NIPT L12345678A", data)
        self.assertIn(b"20%", data)

    def test_registered_without_vat(self):
        hs = self.status("no_vat")
        self.assertEqual((hs.registered, hs.charges_vat, hs.vat_rate, hs.fiscal_enabled), (True, False, 0, True))
        data = printing.receipt_document(self.paid_order(), Printer(name="p", paper_width=80))
        self.assertIn(b"NIPT L12345678A", data)
        self.assertNotIn(b"20%", data)

    def test_not_registered_has_no_tax_anywhere(self):
        hs = self.status("none")
        self.assertEqual((hs.registered, hs.charges_vat, hs.fiscal_enabled, hs.fiscal_configured), (False, False, False, False))
        order = self.paid_order()
        data = printing.receipt_document(order, Printer(name="p", paper_width=80))
        self.assertNotIn(b"NIPT", data)
        self.assertFalse(order.fiscal_documents.exists())

        self.client.login(username="boss", password=PASSWORD)
        page = self.client.get(reverse("outlets:receipt", args=[order.pk]))
        self.assertNotContains(page, "NIPT")
        self.assertNotContains(page, 'href="/fiscal/"')
        r = self.client.get(reverse("core:settings") + "?tab=fiscal")
        self.assertRedirects(r, reverse("core:settings") + "?tab=business", fetch_redirect_response=False)
        settings_page = self.client.get(reverse("core:settings"))
        self.assertNotContains(settings_page, "?tab=fiscal")

        res = self.make_reservation(start=0, nights=1)
        res = fd.check_in(res, self.reception)
        fd.check_out(res, self.reception, allow_balance=True)
        invoice = self.client.get(reverse("frontdesk:invoice", args=[res.pk]))
        self.assertNotContains(invoice, "NIPT")
        self.assertEqual(invoice.context["vat"], Decimal("0"))

    def test_settings_form_needs_a_rate_for_vat(self):
        self.client.login(username="boss", password=PASSWORD)
        hs = HotelSettings.load()
        data = {
            "name": hs.name, "tax_status": "vat", "vat_rate": "0", "currency": "EUR", "currency_symbol": "€",
            "default_language": "sq", "day_ends_at": "0", "check_in_time": "14:00", "check_out_time": "11:00",
        }
        r = self.client.post(reverse("core:settings") + "?tab=business", data)
        self.assertEqual(r.status_code, 200)
        self.assertIn("vat_rate", r.context["form"].errors)
        data["tax_status"] = "no_vat"
        r = self.client.post(reverse("core:settings") + "?tab=business", data)
        self.assertEqual(r.status_code, 302)
        clear_settings_cache()
        self.assertEqual(HotelSettings.load().tax_status, "no_vat")

    def test_setup_wizard_answer(self):
        hs = apply_setup(
            SetupAnswers(business_type="restaurant", name="Kafe e Shoqatës", modules={"outlets"}, tax_status="none"),
            self.manager,
        )
        self.assertEqual((hs.tax_status, hs.vat_rate, hs.registered), ("none", Decimal("0"), False))
