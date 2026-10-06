import json
from decimal import Decimal

from django.urls import reverse

from apps.accounts.models import User
from apps.core import backup
from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings
from apps.core.setup import SetupAnswers, apply_setup
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Charge, DayClose, Expense, Payment
from apps.frontdesk import services as fd
from apps.frontdesk.models import Reservation, Room
from apps.outlets import services as pos
from apps.outlets.models import Item, Order, Outlet, Table


class SetupWizardTests(HotelTestCase):
    def test_restaurant_setup_switches_off_rooms_and_creates_outlets(self):
        apply_setup(
            SetupAnswers(business_type="restaurant", name="Bar Demo", modules={"outlets"}, outlets={"bar", "cafe"}),
            self.manager,
        )
        hs = HotelSettings.load()
        self.assertFalse(hs.module_rooms)
        self.assertTrue(Outlet.objects.filter(kind="bar").exists())
        self.assertTrue(Outlet.objects.get(kind="bar").tables.exists())
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("frontdesk:rack")).status_code, 403)
        self.assertEqual(self.client.get(reverse("outlets:home")).status_code, 200)

    def test_rooms_are_only_generated_into_an_empty_hotel(self):
        before = Room.objects.count()
        apply_setup(
            SetupAnswers(business_type="hotel", name="H", modules={"rooms"}, floors=3, rooms_per_floor=5), self.manager
        )
        self.assertEqual(Room.objects.count(), before)

    def test_managers_are_sent_to_setup_until_done(self):
        hs = HotelSettings.load()
        hs.setup_completed = False
        hs.save()
        self.client.force_login(self.manager)
        self.assertRedirects(self.client.get(reverse("core:dashboard")), reverse("core:setup"))
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)


class FirstRunTests(HotelTestCase):
    def test_first_account_becomes_manager(self):
        User.objects.all().delete()
        self.assertRedirects(self.client.get(reverse("accounts:login")), reverse("accounts:first_run"))
        resp = self.client.post(
            reverse("accounts:first_run"),
            {"first_name": "Arta", "username": "arta", "password1": PASSWORD, "password2": PASSWORD},
        )
        self.assertRedirects(resp, reverse("core:setup"), fetch_redirect_response=False)
        user = User.objects.get(username="arta")
        self.assertTrue(user.is_manager and user.is_superuser)

    def test_first_run_is_closed_once_users_exist(self):
        self.assertRedirects(self.client.get(reverse("accounts:first_run")), reverse("accounts:login"))


class FloorPlanTests(HotelTestCase):
    def save(self, tables):
        self.client.force_login(self.manager)
        return self.client.post(
            reverse("outlets:floor_plan_save", args=[self.restaurant.pk]),
            data=json.dumps({"tables": tables}),
            content_type="application/json",
        )

    def test_rename_swap_resize_and_add(self):
        t2 = Table.objects.create(outlet=self.restaurant, name="2")
        resp = self.save(
            [
                {
                    "id": self.table.pk,
                    "name": "2",
                    "seats": 6,
                    "shape": "round",
                    "zone": "Terrace",
                    "x": 990,
                    "y": 10,
                    "w": 120,
                    "h": 120,
                },
                {"id": t2.pk, "name": "1", "seats": 2, "shape": "square", "zone": "", "x": 0, "y": 0, "w": 90, "h": 90},
                {
                    "id": None,
                    "name": "VIP",
                    "seats": 8,
                    "shape": "long",
                    "zone": "",
                    "x": 300,
                    "y": 300,
                    "w": 200,
                    "h": 90,
                },
            ]
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.table.refresh_from_db()
        self.assertEqual((self.table.name, self.table.seats, self.table.zone), ("2", 6, "Terrace"))
        self.assertEqual(self.table.pos_x, 1000 - 120)  # kept inside the plan
        self.assertTrue(Table.objects.filter(outlet=self.restaurant, name="VIP").exists())

    def test_duplicate_names_are_refused(self):
        resp = self.save([{"id": self.table.pk, "name": "5"}, {"id": None, "name": "5"}])
        self.assertEqual(resp.status_code, 400)

    def test_tables_with_open_orders_cannot_be_removed(self):
        pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        resp = self.save([])
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Table.objects.filter(pk=self.table.pk).exists())


class PosUpgradeTests(HotelTestCase):
    def order_with(self, *items):
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        for item in items:
            pos.add_item(order, item, user=self.waiter)
        return order

    def test_split_and_mixed_payments_close_the_bill_once_paid(self):
        order = self.order_with(self.dish, self.dish)  # 22.00
        pos.pay_order(order, method="cash", amount=Decimal("10"), tendered=Decimal("20"), user=self.waiter)
        order.refresh_from_db()
        self.assertTrue(order.is_open)
        self.assertEqual(order.remaining, Decimal("12.00"))
        with self.assertRaises(BusinessError):
            pos.pay_order(order, method="card", amount=Decimal("15"), user=self.waiter)
        pos.pay_order(order, method="card", user=self.waiter)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(Charge.objects.get(order=order).amount, Decimal("22.00"))
        self.assertEqual(Payment.objects.filter(order=order).first().change, Decimal("10.00"))
        self.assertTrue(order.receipt_number)

    def test_receipt_numbers_are_sequential(self):
        a = self.order_with(self.dish)
        pos.pay_order(a, method="cash", user=self.waiter)
        b = pos.open_order(self.restaurant, label="Takeaway", user=self.waiter)
        pos.add_item(b, self.wine, user=self.waiter)
        pos.pay_order(b, method="cash", user=self.waiter)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(int(b.receipt_number.split("-")[1]), int(a.receipt_number.split("-")[1]) + 1)

    def test_discount_limits_for_staff(self):
        order = self.order_with(self.dish)
        with self.assertRaises(BusinessError):
            pos.set_discount(order, user=self.waiter, percent=Decimal("10"), reason="friend")
        hs = HotelSettings.load()
        hs.max_staff_discount = 10
        hs.save()
        pos.set_discount(order, user=self.waiter, percent=Decimal("10"), reason="regular")
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal("9.90"))
        with self.assertRaises(BusinessError):
            pos.set_discount(order, user=self.waiter, percent=Decimal("50"), reason="x")
        pos.set_discount(order, user=self.manager, percent=Decimal("50"), reason="complaint")
        with self.assertRaises(BusinessError):
            pos.set_discount(order, user=self.manager, amount=Decimal("1"), reason="")

    def test_move_and_merge(self):
        t2 = Table.objects.create(outlet=self.restaurant, name="2")
        t3 = Table.objects.create(outlet=self.restaurant, name="3")
        order = self.order_with(self.dish)
        pos.move_order(order, t2, user=self.waiter)
        order.refresh_from_db()
        self.assertEqual(order.table, t2)
        other = pos.open_order(self.restaurant, table=t3, user=self.waiter)
        pos.add_item(other, self.wine, user=self.waiter)
        merged = pos.move_order(other, t2, user=self.waiter)
        self.assertEqual(merged.pk, order.pk)
        self.assertEqual(merged.total, Decimal("15.50"))
        other.refresh_from_db()
        self.assertEqual(other.status, Order.Status.CANCELLED)

    def test_void_receipt_reverses_revenue(self):
        order = self.order_with(self.dish)
        pos.pay_order(order, method="cash", user=self.waiter)
        with self.assertRaises(BusinessError):
            pos.void_receipt(order, user=self.waiter, reason="wrong")
        pos.void_receipt(order, user=self.manager, reason="Wrong table")
        self.assertFalse(Charge.objects.filter(order=order, voided=False).exists())
        self.assertFalse(Payment.objects.filter(order=order, voided=False).exists())

    def test_partial_payment_then_charge_rest_to_room(self):
        res = self.make_reservation(status=Reservation.Status.CHECKED_IN)
        order = self.order_with(self.dish, self.wine)  # 15.50
        pos.pay_order(order, method="cash", amount=Decimal("5.50"), user=self.waiter)
        pos.charge_to_room(order, res, user=self.waiter)
        self.assertEqual(res.folio.balance, Decimal("10.00"))
        self.assertEqual(sum(c.amount for c in Charge.objects.filter(order=order)), Decimal("15.50"))


class InvoiceNumberTests(HotelTestCase):
    def test_settled_folio_gets_invoice_number(self):
        res = self.make_reservation(start=-1, nights=1, status=Reservation.Status.CHECKED_IN)
        fd.post_accommodation(res, self.reception)
        fd.add_payment(res.folio, amount=Decimal("80"), method="card", user=self.reception)
        fd.check_out(res, self.reception)
        res.folio.refresh_from_db()
        self.assertRegex(res.folio.invoice_number, r"^\d{4}-\d{6}$")

    def test_move_room(self):
        res = self.make_reservation(status=Reservation.Status.CHECKED_IN)
        fd.move_room(res, self.room2, self.reception)
        res.refresh_from_db()
        self.assertEqual(res.room, self.room2)
        self.room.refresh_from_db()
        self.assertEqual(self.room.hk_status, Room.HKStatus.DIRTY)


class FinanceToolTests(HotelTestCase):
    def test_day_close_expected_cash(self):
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter)
        pos.pay_order(order, method="cash", user=self.waiter)  # +11 cash
        Expense.objects.create(description="Bread", amount=Decimal("3"), method="cash", category="food_drink")
        self.client.force_login(self.accountant)
        resp = self.client.post(reverse("finance:day_close"), {"opening_float": "50", "counted_cash": "57"})
        self.assertEqual(resp.status_code, 302)
        close = DayClose.objects.get()
        self.assertEqual(close.expected_cash, Decimal("58.00"))
        self.assertEqual(close.difference, Decimal("-1.00"))

    def test_finance_pages_render(self):
        self.client.force_login(self.accountant)
        for name in (
            "finance:dashboard",
            "finance:day_close",
            "finance:expenses",
            "finance:expense_create",
            "finance:sales",
        ):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class MenuTests(HotelTestCase):
    def test_public_menu_and_sold_out(self):
        url = reverse("menu:public", args=[self.restaurant.menu_token])
        resp = self.client.get(url)
        self.assertContains(resp, "Tavë kosi")
        Item.objects.filter(pk=self.dish.pk).update(is_active=False)
        self.assertNotContains(self.client.get(url), "Tavë kosi")
        Outlet.objects.filter(pk=self.restaurant.pk).update(menu_public=False)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_menu_admin_shows_qr(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("outlets:menu_admin", args=[self.restaurant.pk]))
        self.assertContains(resp, "<svg")


class BackupTests(HotelTestCase):
    def test_full_backup_round_trip(self):
        res = self.make_reservation()
        fd.add_payment(res.folio, amount=Decimal("20"), method="cash", user=self.reception)
        data = backup.export_full()
        counts_before = (
            Reservation.objects.count(),
            Payment.objects.count(),
            User.objects.count(),
            Table.objects.count(),
        )
        doc = backup.read_file(data)
        backup.restore_full(doc)
        counts_after = (
            Reservation.objects.count(),
            Payment.objects.count(),
            User.objects.count(),
            Table.objects.count(),
        )
        self.assertEqual(counts_before, counts_after)
        self.assertTrue(User.objects.get(username="desk").check_password(PASSWORD))

    def test_every_model_is_in_the_full_backup(self):
        from django.apps import apps as django_apps

        ours = {m._meta.label for m in django_apps.get_models() if m.__module__.startswith("apps.")}
        self.assertEqual(ours - set(backup.FULL_MODELS) - backup.NOT_BACKED_UP, set())

    def test_full_backup_keeps_stations_and_seasons(self):
        from apps.frontdesk.models import SeasonRate
        from apps.outlets.models import Category, Printer, Station

        printer = Printer.objects.create(name="Kitchen printer", address="10.0.0.9")
        station = Station.objects.create(name="Kitchen", printer=printer)
        Category.objects.filter(outlet=self.restaurant).update(station=station)
        SeasonRate.objects.create(name="Summer", start_date=self.today, end_date=self.today, percent=10)
        doc = backup.read_file(backup.export_full())
        backup.restore_full(doc)
        self.assertEqual(Category.objects.get(outlet=self.restaurant).station.printer.address, "10.0.0.9")
        self.assertTrue(SeasonRate.objects.filter(name="Summer").exists())

    def test_settings_export_carries_stations_printers_and_seasons(self):
        from apps.frontdesk.models import SeasonRate
        from apps.outlets.models import Category, Printer, Station

        printer = Printer.objects.create(name="Bar printer", address="10.0.0.8")
        station = Station.objects.create(name="Bar", printer=printer)
        Category.objects.filter(outlet=self.restaurant).update(station=station)
        SeasonRate.objects.create(
            name="Peak", room_type=self.double, start_date=self.today, end_date=self.today, rate=Decimal("99")
        )
        data = backup.export_settings()
        Category.objects.update(station=None)
        Station.objects.all().delete()
        Printer.objects.all().delete()
        SeasonRate.objects.all().delete()
        backup.import_settings(backup.read_file(data))
        self.assertEqual(Category.objects.get(outlet=self.restaurant).station.printer.address, "10.0.0.8")
        self.assertEqual(SeasonRate.objects.get().rate, Decimal("99.00"))

    def test_settings_export_import(self):
        data = backup.export_settings()
        Item.objects.all().delete()
        Table.objects.all().delete()
        stats = backup.import_settings(backup.read_file(data))
        self.assertEqual(stats["items"], 2)
        self.assertTrue(Table.objects.filter(outlet=self.restaurant, name="1").exists())

    def test_rejects_other_files(self):
        with self.assertRaises(backup.BackupError):
            backup.read_file(b"hello")

    def test_settings_pages_render(self):
        self.client.force_login(self.manager)
        for tab in ("business", "receipts", "modules", "backup"):
            with self.subTest(tab=tab):
                self.assertEqual(self.client.get(reverse("core:settings") + f"?tab={tab}").status_code, 200)
        self.assertEqual(self.client.get(reverse("core:backup_download", args=["full"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("core:help")).status_code, 200)
