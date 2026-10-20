from decimal import Decimal as D

from django.urls import reverse

from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase
from apps.inventory import transfers
from apps.inventory.models import StockItem, StockTransfer


class TransferTests(HotelTestCase):
    def setUp(self):
        hs = HotelSettings.load()
        hs.module_inventory = True
        hs.save()
        self.beer = StockItem.objects.create(name="Birra Korça 0.5L", unit="pcs", on_hand=D("48"), cost=D("0.85"))
        self.cola = StockItem.objects.create(name="Coca-Cola 0.33L", unit="pcs", on_hand=D("10"), cost=D("0.55"))

    def test_send_then_receive_elsewhere(self):
        t = transfers.send({self.beer.pk: D("24"), self.cola.pk: D("6")}, to="Bar Blloku", user=self.manager)
        self.beer.refresh_from_db()
        self.assertEqual(self.beer.on_hand, D("24"))
        self.assertEqual(t.total, D("23.70"))
        code = transfers.encode(t)
        # "The other business": same database here, so move the goods back as if received there.
        data = transfers.decode(code)
        self.assertEqual((data["code"], data["from"]), (t.code, HotelSettings.load().name))
        lines = transfers.preview(data)
        self.assertEqual(lines[0].match, self.beer)
        received = transfers.receive(data, [ln.match.pk if ln.match else None for ln in lines], user=self.manager)
        self.beer.refresh_from_db()
        self.assertEqual(self.beer.on_hand, D("48"))
        self.assertEqual(received.delivery.total, D("23.70"))
        with self.assertRaises(BusinessError):
            transfers.receive(data, [None, None], user=self.manager)  # only once

    def test_cannot_send_more_than_in_stock_or_nothing(self):
        with self.assertRaises(BusinessError):
            transfers.send({self.cola.pk: D("11")}, to="Bar", user=self.manager)
        with self.assertRaises(BusinessError):
            transfers.send({}, to="Bar", user=self.manager)
        with self.assertRaises(BusinessError):
            transfers.send({self.cola.pk: D("1")}, to="", user=self.manager)

    def test_damaged_or_foreign_codes(self):
        for bad in ("hello", "IKT1.!!!", "IKT1.eJwLSS0u0c3JTEtJ5S9IrUhOLUhVBACBLAke"):
            with self.assertRaises(BusinessError):
                transfers.decode(bad)

    def test_new_item_is_created_when_not_matched(self):
        t = transfers.send({self.cola.pk: D("2")}, to="Bar", user=self.manager)
        data = transfers.decode(transfers.encode(t))
        data["lines"][0]["name"] = "Cola Zero"
        transfers.receive(data, [None], user=self.manager)
        self.assertEqual(StockItem.objects.get(name="Cola Zero").on_hand, D("2"))

    def test_pages(self):
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.post(reverse("inventory:transfer_send"), {"to": "Bar Blloku", f"q{self.beer.pk}": "12"})
        t = StockTransfer.objects.get(direction="out")
        self.assertRedirects(r, reverse("inventory:transfer_detail", args=[t.pk]), fetch_redirect_response=False)
        page = self.client.get(reverse("inventory:transfer_detail", args=[t.pk]))
        self.assertContains(page, "IKT1.")
        code = self.client.get(reverse("inventory:transfer_detail", args=[t.pk]) + "?download=1").content.decode().strip()
        r = self.client.post(reverse("inventory:transfer_receive"), {"code": code})
        self.assertContains(r, "Birra Korça 0.5L")
        self.client.post(reverse("inventory:transfer_receive"), {"code": code, "confirm": "1", "m0": str(self.beer.pk)})
        self.assertTrue(StockTransfer.objects.filter(direction="in", code=t.code).exists())
        self.assertContains(self.client.get(reverse("inventory:transfers")), t.code)

    def test_usage_report_counts_transfers(self):
        from apps.inventory import services

        transfers.send({self.beer.pk: D("6")}, to="Bar", user=self.manager)
        row = next(r for r in services.usage(self.today, self.today) if r["item"] == self.beer)
        self.assertEqual(row["sent"], D("6"))
        self.client.login(username="boss", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("inventory:usage")).status_code, 200)
