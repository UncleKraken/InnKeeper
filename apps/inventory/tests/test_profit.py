from decimal import Decimal

from django.urls import reverse

from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import PASSWORD, HotelTestCase
from apps.inventory import profit
from apps.inventory.models import RecipeLine, StockItem
from apps.outlets import services as pos


class MenuProfitTests(HotelTestCase):
    def setUp(self):
        HotelSettings.objects.update(vat_rate=Decimal("20"), tax_status="vat")
        clear_settings_cache()
        lamb = StockItem.objects.create(name="Lamb", unit="kg", cost=Decimal("10"))
        yog = StockItem.objects.create(name="Yogurt", unit="kg", cost=Decimal("2"))
        RecipeLine.objects.create(item=self.dish, stock_item=lamb, quantity=Decimal("0.25"))
        RecipeLine.objects.create(item=self.dish, stock_item=yog, quantity=Decimal("0.5"))
        order = pos.open_order(self.restaurant, user=self.waiter, table=self.table)
        pos.add_item(order, self.dish, user=self.waiter, quantity=2)
        pos.add_item(order, self.wine, user=self.waiter)
        pos.pay_order(order, method="cash", user=self.waiter)

    def test_numbers(self):
        rows = {r["item"].name: r for r in profit.rows(self.today, self.today)}
        dish = rows["Tavë kosi"]
        # 11.00 incl. 20% VAT → 9.17 net; cost 2.50 + 1.00 = 3.50
        self.assertEqual((dish["net_price"], dish["cost"], dish["margin"], dish["pct"]), (Decimal("9.17"), Decimal("3.50"), Decimal("5.67"), Decimal("62")))
        self.assertEqual((dish["qty"], dish["profit"]), (2, Decimal("11.33")))
        self.assertFalse(rows["Wine"]["has_recipe"])
        self.assertIsNone(rows["Wine"]["profit"])
        self.assertTrue(dish["low"] is False)

    def test_page_and_excel(self):
        self.client.login(username="boss", password=PASSWORD)
        page = self.client.get(reverse("inventory:menu_profit"))
        self.assertContains(page, "62%")
        self.assertEqual(page.context["missing"], 1)
        r = self.client.get(reverse("inventory:menu_profit") + "?format=xlsx&sort=pct")
        self.assertTrue(r.content.startswith(b"PK"))
