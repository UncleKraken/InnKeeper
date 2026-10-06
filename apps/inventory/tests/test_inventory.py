from decimal import Decimal

from django.urls import reverse

from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Expense
from apps.inventory import services
from apps.inventory.models import RecipeLine, StockItem, StockMove, Supplier
from apps.outlets import services as pos

D = Decimal


class StockTests(HotelTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.lamb = StockItem.objects.create(name="Lamb", unit=StockItem.Unit.KG, min_level=D("1"))
        cls.yoghurt = StockItem.objects.create(name="Yoghurt", unit=StockItem.Unit.KG)
        RecipeLine.objects.create(item=cls.dish, stock_item=cls.lamb, quantity=D("0.25"))
        RecipeLine.objects.create(item=cls.dish, stock_item=cls.yoghurt, quantity=D("0.3"))
        cls.supplier = Supplier.objects.create(name="Market")

    def receive(self, item, qty, cost, **kw):
        return services.receive_delivery([services.DeliveryLine(item, D(qty), D(cost))], user=self.manager, **kw)

    def test_delivery_adds_stock_and_averages_cost(self):
        self.receive(self.lamb, "4", "10", supplier=self.supplier)
        self.receive(self.lamb, "4", "12")
        self.lamb.refresh_from_db()
        self.assertEqual(self.lamb.on_hand, D("8"))
        self.assertEqual(self.lamb.cost, D("11"))
        self.assertEqual(self.lamb.supplier, self.supplier)

    def test_delivery_can_record_an_expense(self):
        d = self.receive(self.lamb, "2", "9.50", record_expense=True, paid_with="card", reference="F-1")
        self.assertEqual(d.total, D("19.00"))
        exp = Expense.objects.get()
        self.assertEqual((exp.amount, exp.method, exp.category), (D("19.00"), "card", Expense.Category.FOOD_DRINK))

    def test_empty_delivery_is_refused(self):
        with self.assertRaises(BusinessError):
            services.receive_delivery([], user=self.manager)

    def test_paying_a_bill_takes_ingredients_out_and_void_puts_them_back(self):
        self.receive(self.lamb, "5", "10")
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter, quantity=2)
        pos.add_item(order, self.wine, user=self.waiter)  # no recipe: no stock change
        pos.pay_order(order, method="cash", user=self.waiter)
        self.lamb.refresh_from_db()
        self.yoghurt.refresh_from_db()
        self.assertEqual(self.lamb.on_hand, D("4.5"))
        self.assertEqual(self.yoghurt.on_hand, D("-0.6"))  # sold without stock recorded: shows negative
        # Calling again does not double count.
        self.assertEqual(services.consume_for_order(order), 0)
        pos.void_receipt(order, user=self.manager, reason="wrong table")
        self.lamb.refresh_from_db()
        self.assertEqual(self.lamb.on_hand, D("5"))
        self.assertEqual(services.return_for_order(order), 0)

    def test_room_charge_also_takes_stock(self):
        from apps.frontdesk.models import Reservation

        res = self.make_reservation(status=Reservation.Status.CHECKED_IN)
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter)
        pos.charge_to_room(order, res, user=self.waiter)
        self.lamb.refresh_from_db()
        self.assertEqual(self.lamb.on_hand, D("-0.25"))

    def test_nothing_changes_when_stock_is_switched_off(self):
        hs = HotelSettings.load()
        hs.module_inventory = False
        hs.save()
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter)
        pos.pay_order(order, method="cash", user=self.waiter)
        self.assertFalse(StockMove.objects.exists())

    def test_waste_needs_a_reason(self):
        self.receive(self.lamb, "2", "10")
        with self.assertRaises(BusinessError):
            services.record_waste(self.lamb, D("1"), user=self.manager, reason=" ")
        services.record_waste(self.lamb, D("1"), user=self.manager, reason="dropped")
        self.lamb.refresh_from_db()
        self.assertEqual(self.lamb.on_hand, D("1"))
        self.assertTrue(self.lamb.is_low)

    def test_count_sets_stock_and_values_the_difference(self):
        self.receive(self.lamb, "5", "10")
        self.receive(self.yoghurt, "2", "2")
        count = services.apply_count({self.lamb.pk: D("4.5"), self.yoghurt.pk: D("2")}, user=self.manager)
        self.lamb.refresh_from_db()
        self.assertEqual(self.lamb.on_hand, D("4.5"))
        self.assertEqual(count.difference_value, D("-5.00"))
        self.assertEqual(count.moves.count(), 1)  # yoghurt matched

    def test_usage_report_and_recipe_cost(self):
        self.receive(self.lamb, "5", "10")
        self.receive(self.yoghurt, "5", "2")
        self.assertEqual(services.recipe_cost(self.dish), D("3.10"))
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter)
        pos.pay_order(order, method="cash", user=self.waiter)
        rows = {r["item"].name: r for r in services.usage(self.today, self.today)}
        self.assertEqual(rows["Lamb"]["used"], D("0.25"))
        self.assertEqual(rows["Lamb"]["used_value"], D("2.50"))
        self.assertEqual(rows["Lamb"]["received"], D("5"))

    def test_pages_and_permissions(self):
        self.receive(self.lamb, "5", "10")
        self.client.login(username="money", password=PASSWORD)  # finance role
        for name, args in [
            ("inventory:stock", []),
            ("inventory:item_detail", [self.lamb.pk]),
            ("inventory:delivery_list", []),
            ("inventory:delivery_create", []),
            ("inventory:count_list", []),
            ("inventory:count_create", []),
            ("inventory:recipes", []),
            ("inventory:recipe_edit", [self.dish.pk]),
            ("inventory:usage", []),
            ("inventory:supplier_list", []),
            ("inventory:item_create", []),
        ]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        self.client.login(username="waiter", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("inventory:stock")).status_code, 403)

    def test_delivery_form_and_count_form(self):
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.post(
            reverse("inventory:delivery_create"),
            {
                "item": [self.lamb.pk, self.yoghurt.pk, ""],
                "qty": ["3", "1,5", ""],
                "cost": ["10", "2", ""],
                "supplier": self.supplier.pk,
                "business_date": self.today.isoformat(),
                "paid_with": "cash",
            },
        )
        self.assertEqual(r.status_code, 302)
        self.yoghurt.refresh_from_db()
        self.assertEqual(self.yoghurt.on_hand, D("1.5"))
        self.assertFalse(Expense.objects.exists())  # box left unticked
        r = self.client.post(reverse("inventory:count_create"), {f"c{self.lamb.pk}": "2.5", "note": "Friday"})
        self.assertEqual(r.status_code, 302)
        self.lamb.refresh_from_db()
        self.assertEqual(self.lamb.on_hand, D("2.5"))

    def test_recipe_edit_and_track_as_stock(self):
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(
            reverse("inventory:recipe_edit", args=[self.dish.pk]),
            {"stock": [self.lamb.pk, ""], "qty": ["0.3", ""]},
        )
        self.assertEqual(list(self.dish.recipe.values_list("stock_item__name", "quantity")), [("Lamb", D("0.300"))])
        self.client.post(reverse("inventory:recipe_track", args=[self.wine.pk]))
        line = self.wine.recipe.get()
        self.assertEqual((line.stock_item.name, line.quantity), ("Wine", D("1.000")))

    def test_new_item_with_opening_stock(self):
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(
            reverse("inventory:item_create"),
            {
                "name": "Soap",
                "group": "amenities",
                "unit": "pcs",
                "min_level": "10",
                "cost": "0.3",
                "opening": "40",
                "is_active": "on",
            },
        )
        soap = StockItem.objects.get(name="Soap")
        self.assertEqual(soap.on_hand, D("40"))
        self.assertEqual(soap.moves.get().kind, StockMove.Kind.ADJUST)


class StockSettingsExportTests(HotelTestCase):
    def test_settings_export_carries_stock_items_and_recipes(self):
        from apps.core import backup

        sup = Supplier.objects.create(name="Market")
        lamb = StockItem.objects.create(name="Lamb", unit="kg", supplier=sup, cost=D("9"), on_hand=D("3"))
        RecipeLine.objects.create(item=self.dish, stock_item=lamb, quantity=D("0.25"))
        data = backup.export_settings()
        RecipeLine.objects.all().delete()
        StockItem.objects.all().delete()
        Supplier.objects.all().delete()
        backup.import_settings(backup.read_file(data))
        lamb = StockItem.objects.get(name="Lamb")
        self.assertEqual((lamb.supplier.name, lamb.cost, lamb.on_hand), ("Market", D("9"), D("0")))
        self.assertEqual(self.dish.recipe.get().quantity, D("0.250"))
