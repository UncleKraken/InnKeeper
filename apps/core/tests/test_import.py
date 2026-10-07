from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core import importer
from apps.core.testing import PASSWORD, HotelTestCase
from apps.frontdesk.models import Guest
from apps.inventory.models import StockItem
from apps.outlets.models import Item, Outlet


class ImportTests(HotelTestCase):
    def test_menu_with_albanian_headers_semicolons_and_comma_decimals(self):
        raw = "Pika;Kategoria;Emri;Çmimi;Emri anglisht\nRestaurant;Mains;Tavë kosi;12,50;Baked lamb\nBar;Kafe;Espresso;1,5;\n"
        parsed = importer.parse("menu", raw.encode("utf-8-sig"))
        self.assertEqual(parsed.errors, [])
        stats = importer.apply(parsed, self.manager)
        self.assertEqual(stats, {"created": 1, "updated": 1})  # Tavë kosi existed
        self.dish.refresh_from_db()
        self.assertEqual((self.dish.price, self.dish.name_en), (Decimal("12.50"), "Baked lamb"))
        self.assertTrue(
            Item.objects.filter(name="Espresso", category__outlet__name="Bar", price=Decimal("1.50")).exists()
        )
        self.assertEqual(Outlet.objects.filter(name="Bar").count(), 1)

    def test_bad_rows_are_reported_and_skipped(self):
        raw = b"outlet,category,name,price\nRestaurant,Mains,Soup,abc\nRestaurant,Mains,Salad,5\n"
        parsed = importer.parse("menu", raw)
        self.assertEqual(len(parsed.rows), 1)
        self.assertIn("2", parsed.errors[0])

    def test_missing_columns(self):
        parsed = importer.parse("menu", b"name,price\nSoup,4\n")
        self.assertTrue(parsed.errors)
        self.assertEqual(parsed.rows, [])

    def test_stock_sets_quantity_with_a_movement(self):
        raw = "name;group;unit;in stock;cost;supplier\nBeer 0.5L;Drinks;bottle;48;0,85;Birra Korça\n"
        importer.apply(importer.parse("stock", raw.encode()), self.manager)
        item = StockItem.objects.get(name="Beer 0.5L")
        self.assertEqual(
            (item.on_hand, item.unit, item.group, item.supplier.name),
            (Decimal("48"), "bottle", "drinks", "Birra Korça"),
        )
        self.assertEqual(item.moves.count(), 1)

    def test_guests_with_dates_and_cp1252(self):
        raw = "first_name;last_name;nationality;document_type;document_number;date_of_birth\nÉlise;Dupont;FR;Passport;12AB;31.12.1990\n"
        importer.apply(importer.parse("guests", raw.encode("cp1252")), self.manager)
        g = Guest.objects.get(last_name="Dupont")
        self.assertEqual((g.first_name, g.document_type, str(g.date_of_birth)), ("Élise", "passport", "1990-12-31"))

    def test_upload_preview_and_confirm(self):
        self.client.login(username="boss", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("core:settings") + "?tab=import").status_code, 200)
        self.assertEqual(self.client.get(reverse("core:import_template", args=["menu"])).status_code, 200)
        f = SimpleUploadedFile("menu.csv", b"outlet;category;name;price\nRestaurant;Mains;Fergese;9\n", "text/csv")
        page = self.client.post(reverse("core:import_file"), {"kind": "menu", "file": f})
        self.assertContains(page, "Fergese")
        self.assertFalse(Item.objects.filter(name="Fergese").exists())
        self.client.post(reverse("core:import_file"), {"kind": "menu", "file": page.context["file"], "confirm": "1"})
        self.assertTrue(Item.objects.filter(name="Fergese").exists())

    def test_xlsx_is_explained(self):
        self.client.login(username="boss", password=PASSWORD)
        f = SimpleUploadedFile("menu.xlsx", b"PK\x03\x04rest", "application/octet-stream")
        r = self.client.post(reverse("core:import_file"), {"kind": "menu", "file": f}, follow=True)
        self.assertContains(r, "CSV UTF-8")
