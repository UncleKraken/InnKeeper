from django.urls import reverse

from apps.core.testing import PASSWORD, HotelTestCase
from apps.outlets import printing
from apps.outlets import services as pos
from apps.outlets.models import Printer


class BillLanguageTests(HotelTestCase):
    def setUp(self):
        self.dish.name_en = "Baked lamb"
        self.dish.save()
        self.order = pos.open_order(self.restaurant, user=self.waiter, table=self.table)
        pos.add_item(self.order, self.dish, user=self.waiter)
        pos.pay_order(self.order, method="cash", user=self.waiter)
        self.client.login(username="boss", password=PASSWORD)

    def test_receipt_page_in_english_and_albanian(self):
        en = self.client.get(reverse("outlets:receipt", args=[self.order.pk]) + "?lang=en")
        self.assertContains(en, "Baked lamb")
        self.assertContains(en, "Receipt")
        sq = self.client.get(reverse("outlets:receipt", args=[self.order.pk]) + "?lang=sq")
        self.assertContains(sq, "Tavë kosi")
        self.assertContains(sq, "Kupon")

    def test_thermal_receipt_in_english(self):
        p = Printer(name="Bar", paper_width=80)
        data = printing.receipt_document(self.order, p, language="en")
        self.assertIn(b"Baked lamb", data)
        self.assertIn(b"TOTAL", data)

    def test_guest_invoice_in_english(self):
        from apps.finance.models import Folio

        res = self.make_reservation()
        folio, _ = Folio.objects.get_or_create(reservation=res)
        r = self.client.get(reverse("frontdesk:invoice", args=[res.pk]) + "?lang=en")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "English")
        self.assertEqual(r.context["bill_lang"], "en")

    def test_order_page_offers_the_other_language(self):
        order = pos.open_order(self.restaurant, user=self.waiter, table=self.table)
        pos.add_item(order, self.dish, user=self.waiter)
        page = self.client.get(reverse("outlets:order", args=[order.pk]))
        self.assertContains(page, "lang=en")
