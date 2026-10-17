from datetime import datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.urls import reverse

from apps.core.exceptions import BusinessError
from apps.core.testing import PASSWORD, HotelTestCase
from apps.outlets import printing, pricing, services
from apps.outlets.models import Category, Item, Option, OptionGroup, Printer, PriceRule

D = Decimal
TZ = ZoneInfo("Europe/Tirane")


class OptionTests(HotelTestCase):
    def setUp(self):
        drinks = Category.objects.create(outlet=self.restaurant, name="Kafe")
        self.coffee = Item.objects.create(category=drinks, name="Espresso", price=D("1.00"))
        self.size = OptionGroup.objects.create(name="Size", required=True, sort_order=0)
        self.small = Option.objects.create(group=self.size, name="Small")
        self.large = Option.objects.create(group=self.size, name="Large", price_change=D("0.50"))
        self.extras = OptionGroup.objects.create(name="Extras", multiple=True, sort_order=1)
        self.milk = Option.objects.create(group=self.extras, name="Milk", price_change=D("0.20"))
        self.cream = Option.objects.create(group=self.extras, name="Cream", price_change=D("0.30"))
        self.size.items.add(self.coffee)
        self.extras.items.add(self.coffee)
        self.order = services.open_order(self.restaurant, table=self.table, user=self.waiter)

    def add(self, *options):
        return services.add_item(self.order, self.coffee, user=self.waiter, option_ids=[o.pk for o in options])

    def test_choices_change_price_and_name(self):
        line = self.add(self.large, self.milk, self.cream)
        self.assertEqual((line.name, line.unit_price), ("Espresso · Large, Milk, Cream", D("2.00")))
        self.assertEqual([o["name"] for o in line.options], ["Large", "Milk", "Cream"])

    def test_same_choices_merge_different_ones_dont(self):
        self.add(self.large)
        self.add(self.large)
        self.add(self.small)
        self.assertEqual(sorted((ln.name, ln.quantity) for ln in self.order.lines.all()), [("Espresso · Large", 2), ("Espresso · Small", 1)])

    def test_rules(self):
        with self.assertRaises(BusinessError):
            self.add()  # size is required
        with self.assertRaises(BusinessError):
            self.add(self.small, self.large)  # one size only
        other = OptionGroup.objects.create(name="Other")
        stranger = Option.objects.create(group=other, name="X")
        with self.assertRaises(BusinessError):
            self.add(self.small, stranger)  # not offered with this item

    def test_more_of_a_sent_line_keeps_its_choices(self):
        from apps.outlets.models import OrderLine, Station

        station = Station.objects.create(name="Bar")
        self.coffee.category.station = station
        self.coffee.category.save()
        self.add(self.large)
        services.send_to_kitchen(self.order, user=self.waiter)
        line = self.order.lines.get()
        services.change_quantity(line, 1, user=self.waiter)
        new = OrderLine.objects.exclude(pk=line.pk).get(order=self.order)
        self.assertEqual((new.name, new.unit_price), ("Espresso · Large", D("1.50")))

    def test_kitchen_ticket_and_receipt_show_choices(self):
        from apps.outlets.models import Station

        self.coffee.category.station = Station.objects.create(name="Bar")
        self.coffee.category.save()
        self.add(self.large, self.milk)
        (ticket,) = services.send_to_kitchen(self.order, user=self.waiter)
        self.assertIn("Large, Milk".encode("cp1252"), printing.kitchen_document(ticket, Printer(name="p", paper_width=80)))

    def test_till_page_offers_the_picker(self):
        self.client.login(username="waiter", password=PASSWORD)
        r = self.client.get(reverse("outlets:order", args=[self.order.pk]))
        self.assertIn(self.coffee.pk, r.context["item_options"])
        self.assertContains(r, f'data-options="{self.coffee.pk}"')
        r = self.client.post(
            reverse("outlets:add_item", args=[self.order.pk]),
            {"item": self.coffee.pk, "option": [self.large.pk]},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertIn("Espresso · Large", r.json()["ticket"])

    def test_manager_pages(self):
        self.client.login(username="boss", password=PASSWORD)
        self.assertContains(self.client.get(reverse("outlets:option_list")), "Size")
        r = self.client.post(
            reverse("outlets:option_create"),
            {
                "name": "Sugar", "name_en": "", "sort_order": "0", "items": [self.coffee.pk],
                "options-TOTAL_FORMS": "3", "options-INITIAL_FORMS": "0", "options-MIN_NUM_FORMS": "0", "options-MAX_NUM_FORMS": "1000",
                "options-0-name": "No sugar", "options-0-price_change": "0", "options-0-is_active": "on",
                "options-1-name": "Normal", "options-1-price_change": "0", "options-1-is_active": "on",
                "options-2-name": "", "options-2-price_change": "0", "options-2-is_active": "on",
            },
        )
        self.assertEqual(r.status_code, 302, r.context and (r.context["form"].errors, r.context["formset"].errors))
        group = OptionGroup.objects.get(name="Sugar")
        self.assertEqual([o.name for o in group.options.all()], ["No sugar", "Normal"])
        self.assertIn(self.coffee, group.items.all())
        self.assertEqual(self.client.get(reverse("outlets:option_edit", args=[group.pk])).status_code, 200)


class HappyHourTests(HotelTestCase):
    def setUp(self):
        self.rule = PriceRule.objects.create(name="Happy hour", percent=D("-20"), start_time=time(17), end_time=time(19))
        self.order = services.open_order(self.restaurant, table=self.table, user=self.waiter)

    def at(self, day, hour, minute=0):
        return mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, day, hour, minute, tzinfo=TZ))

    def test_cheaper_during_the_hours_only(self):
        with self.at(16, 18):  # Friday 18:00
            line = services.add_item(self.order, self.wine, user=self.waiter)
        self.assertEqual((line.unit_price, line.price_note), (D("3.60"), "Happy hour −20%"))
        with self.at(16, 19, 30):
            later = services.add_item(self.order, self.wine, user=self.waiter)
        self.assertEqual(later.unit_price, D("4.50"))
        self.assertNotEqual(line.pk, later.pk)  # different prices are separate lines

    def test_days_categories_and_outlets(self):
        self.rule.days = "56"  # weekend only
        self.rule.save()
        with self.at(16, 18):
            self.assertIsNone(pricing.rule_for(self.wine))
        with self.at(17, 18):
            self.assertEqual(pricing.rule_for(self.wine), self.rule)
        other = Category.objects.create(outlet=self.restaurant, name="Food")
        self.rule.categories.add(other)
        with self.at(17, 18):
            self.assertIsNone(pricing.rule_for(self.wine))

    def test_late_night_rule_past_midnight_belongs_to_its_evening(self):
        late = PriceRule.objects.create(name="Late", percent=D("15"), start_time=time(23), end_time=time(3), days="4")
        self.rule.delete()
        with self.at(16, 23, 30):  # Friday night
            self.assertEqual(pricing.rule_for(self.wine), late)
        with self.at(17, 1, 30):  # still Friday's night, early Saturday
            self.assertEqual(pricing.rule_for(self.wine), late)
            self.assertEqual(pricing.adjust(D("4.50"), late), D("5.18"))
        with self.at(18, 1, 30):  # Saturday's night: not Friday
            self.assertIsNone(pricing.rule_for(self.wine))

    def test_manager_page(self):
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.post(
            reverse("outlets:price_rule_create"),
            {"name": "Aperitivo", "percent": "-10", "start_time": "18:00", "end_time": "20:00", "is_active": "on", "weekdays": ["0", "1"]},
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(PriceRule.objects.get(name="Aperitivo").days, "01")
        self.assertContains(self.client.get(reverse("outlets:price_rule_list")), "18:00")


class MenuExtrasExportTests(HotelTestCase):
    def test_settings_export_carries_options_and_happy_hour(self):
        from apps.core import backup

        group = OptionGroup.objects.create(name="Size", required=True)
        Option.objects.create(group=group, name="Large", price_change=D("0.50"))
        group.items.add(self.wine)
        rule = PriceRule.objects.create(name="Happy hour", percent=D("-20"), start_time=time(17), end_time=time(19), days="45")
        rule.outlets.add(self.restaurant)
        doc = backup.read_file(backup.export_settings())
        OptionGroup.objects.all().delete()
        PriceRule.objects.all().delete()
        backup.import_settings(doc)
        group = OptionGroup.objects.get(name="Size")
        self.assertEqual([(o.name, o.price_change) for o in group.options.all()], [("Large", D("0.50"))])
        self.assertIn(self.wine, group.items.all())
        rule = PriceRule.objects.get(name="Happy hour")
        self.assertEqual((rule.days, list(rule.outlets.all())), ("45", [self.restaurant]))
