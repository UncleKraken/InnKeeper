from decimal import Decimal

from django.core import mail
from django.urls import reverse

from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import PASSWORD, HotelTestCase
from apps.inventory import purchasing
from apps.inventory.models import PurchaseOrder, StockItem, Supplier


class PurchaseOrderTests(HotelTestCase):
    def setUp(self):
        self.korca = Supplier.objects.create(name="Birra Korça", phone="069 123 4567", email="orders@korca.test")
        self.beer = StockItem.objects.create(name="Beer 0.5", unit="bottle", min_level=24, on_hand=10, cost=Decimal("0.80"), supplier=self.korca)
        self.flour = StockItem.objects.create(name="Flour", unit="kg", min_level=5, on_hand=Decimal("1.25"))
        self.water = StockItem.objects.create(name="Water", unit="bottle", min_level=12, on_hand=40, supplier=self.korca)
        self.client.login(username="boss", password=PASSWORD)

    def test_suggested_quantities(self):
        self.assertEqual(purchasing.suggested_quantity(self.beer), Decimal("38"))  # back to 48
        self.assertEqual(purchasing.suggested_quantity(self.flour), Decimal("8.8"))

    def test_low_stock_makes_one_draft_per_supplier_once(self):
        r = self.client.post(reverse("inventory:order_low_stock"))
        self.assertEqual(PurchaseOrder.objects.count(), 2)  # Korça + no supplier
        korca = PurchaseOrder.objects.get(supplier=self.korca)
        self.assertEqual([ln.stock_item for ln in korca.lines.all()], [self.beer])  # water isn't low
        self.assertRedirects(r, reverse("inventory:order_list"))
        self.client.post(reverse("inventory:order_low_stock"))
        self.assertEqual(PurchaseOrder.objects.count(), 2)  # already on order

    def test_edit_whatsapp_and_receive_updates_stock(self):
        po = purchasing.orders_for_low_stock(self.manager)[0]
        po = PurchaseOrder.objects.get(supplier=self.korca)
        page = self.client.get(reverse("inventory:order_detail", args=[po.pk]))
        self.assertContains(page, "https://wa.me/355691234567?text=")
        self.client.post(
            reverse("inventory:order_detail", args=[po.pk]),
            {"supplier": self.korca.pk, "note": "Before Friday", "item": [self.beer.pk, self.water.pk, ""], "qty": ["48", "24", ""], "cost": ["0,75", "", ""]},
        )
        self.assertEqual([(ln.stock_item.name, ln.quantity) for ln in po.lines.all()], [("Beer 0.5", 48), ("Water", 24)])
        self.assertIn("48 bottle — Beer 0.5", purchasing.message_text(po).replace("shishe", "bottle"))
        self.client.post(reverse("inventory:order_action", args=[po.pk, "sent"]))
        po.refresh_from_db()
        self.assertEqual(po.status, "sent")
        r = self.client.post(reverse("inventory:order_action", args=[po.pk, "receive"]))
        self.assertRedirects(r, reverse("inventory:delivery_create") + f"?po={po.pk}", fetch_redirect_response=False)
        form = self.client.get(r["Location"])
        self.assertContains(form, po.number)
        self.client.post(
            reverse("inventory:delivery_create"),
            {"po": po.pk, "supplier": self.korca.pk, "business_date": self.today.isoformat(), "reference": po.number,
             "note": "", "paid_with": "cash", "item": [self.beer.pk, self.water.pk], "qty": ["48", "20"], "cost": ["0.75", "0.30"]},
        )
        po.refresh_from_db()
        self.beer.refresh_from_db()
        self.assertEqual((po.status, self.beer.on_hand), ("received", Decimal("58")))
        self.assertIsNotNone(po.delivery)
        self.assertEqual(self.client.get(reverse("inventory:order_detail", args=[po.pk])).status_code, 200)

    def test_email_marks_ordered(self):
        HotelSettings.objects.update(smtp_host="smtp.test", email_from="bar@test.al")
        clear_settings_cache()
        po = PurchaseOrder.objects.create(supplier=self.korca)
        po.lines.create(stock_item=self.beer, quantity=24)
        self.client.post(reverse("inventory:order_action", args=[po.pk, "email"]))
        po.refresh_from_db()
        self.assertEqual((po.status, mail.outbox[0].to), ("sent", ["orders@korca.test"]))
        self.assertIn("Beer 0.5", mail.outbox[0].alternatives[0][0])

    def test_empty_order_cannot_be_sent_and_can_be_cancelled(self):
        po = PurchaseOrder.objects.create(supplier=self.korca)
        self.client.post(reverse("inventory:order_action", args=[po.pk, "sent"]))
        po.refresh_from_db()
        self.assertEqual(po.status, "draft")
        self.client.post(reverse("inventory:order_action", args=[po.pk, "cancel"]))
        po.refresh_from_db()
        self.assertEqual(po.status, "cancelled")

    def test_pages(self):
        purchasing.orders_for_low_stock(self.manager)
        for url in (reverse("inventory:order_list"), reverse("inventory:order_list") + "?show=all", reverse("inventory:order_create"), reverse("inventory:stock")):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        po = PurchaseOrder.objects.first()
        self.assertContains(self.client.get(reverse("inventory:order_print", args=[po.pk])), po.number)
        r = self.client.post(reverse("inventory:order_create"), {"supplier": self.korca.pk, "note": ""})
        self.assertEqual(r.status_code, 302)

    def test_waiter_has_no_access(self):
        self.client.login(username="waiter", password=PASSWORD)
        self.assertNotEqual(self.client.get(reverse("inventory:order_list")).status_code, 200)
