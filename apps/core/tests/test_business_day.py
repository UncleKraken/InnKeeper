from datetime import date, datetime
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.urls import reverse

from apps.core.businessday import business_date, day_range
from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.setup import SetupAnswers, apply_setup
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Charge, Payment
from apps.finance.reports import day_summary
from apps.outlets import services as pos
from apps.outlets.models import Outlet

TIRANE = ZoneInfo("Europe/Tirane")
FRIDAY = date(2026, 10, 9)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TIRANE)


class BusinessDayTests(HotelTestCase):
    def night_bar(self, hour=4):
        HotelSettings.objects.update(day_ends_at=hour)
        clear_settings_cache()

    def sell(self, when, method="cash"):
        with mock.patch("django.utils.timezone.now", return_value=when):
            order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
            pos.add_item(order, self.wine, user=self.waiter, quantity=2)  # 9.00
            pos.pay_order(order, method=method, user=self.waiter)
        return order

    def test_hours_before_the_cut_off_belong_to_the_night_before(self):
        self.night_bar(4)
        self.assertEqual(business_date(at(10, 1, 30)), FRIDAY)
        self.assertEqual(business_date(at(10, 3, 59)), FRIDAY)
        self.assertEqual(business_date(at(10, 4, 0)), date(2026, 10, 10))
        self.assertEqual(day_range(FRIDAY), (at(9, 4), at(10, 4)))

    def test_midnight_by_default(self):
        self.assertEqual(business_date(at(10, 0, 30)), date(2026, 10, 10))

    def test_a_sale_at_half_past_one_is_in_the_nights_day_close(self):
        self.night_bar(4)
        self.sell(at(9, 23, 0))
        order = self.sell(at(10, 1, 30))
        self.assertEqual(Charge.objects.get(order=order).business_date, FRIDAY)
        self.assertEqual(Payment.objects.get(order=order).business_date, FRIDAY)
        friday = day_summary(FRIDAY)
        self.assertEqual((friday["cash"], friday["receipt_count"]), (Decimal("18.00"), 2))
        self.assertEqual(day_summary(date(2026, 10, 10))["receipt_count"], 0)

    def test_a_void_after_midnight_counts_the_same_night(self):
        self.night_bar(4)
        order = self.sell(at(9, 22, 0))
        with mock.patch("django.utils.timezone.now", return_value=at(10, 1, 0)):
            pos.void_receipt(order, user=self.manager, reason="wrong table")
        self.assertEqual(day_summary(FRIDAY)["cash"], Decimal("0"))
        self.assertEqual(day_summary(date(2026, 10, 10))["cash"], Decimal("0"))

    def test_without_a_cut_off_the_calendar_day_counts(self):
        order = self.sell(at(10, 1, 30))
        self.assertEqual(Charge.objects.get(order=order).business_date, date(2026, 10, 10))

    def test_day_close_page_at_night_opens_the_night_before(self):
        self.night_bar(4)
        with mock.patch("django.utils.timezone.now", return_value=at(10, 2, 15)):
            self.client.login(username="boss", password=PASSWORD)  # the session must be valid at that time
            r = self.client.get(reverse("finance:day_close"))
        self.assertEqual(r.context["day"], FRIDAY)

    def test_setting_it_in_business_details(self):
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.get(reverse("core:settings") + "?tab=business")
        self.assertContains(r, "day_ends_at")


class NightlifeSetupTests(HotelTestCase):
    def test_night_bar_setup(self):
        hs = apply_setup(
            SetupAnswers(business_type="nightlife", name="Club Nata", modules={"outlets"}, outlets={"bar"}), self.manager
        )
        self.assertEqual((hs.business_type, hs.day_ends_at), ("nightlife", 5))
        self.assertTrue(Outlet.objects.filter(kind="bar").exists())

    def test_an_answer_overrides_the_usual(self):
        hs = apply_setup(
            SetupAnswers(business_type="restaurant", name="Taverna", modules={"outlets"}, day_ends_at=2), self.manager
        )
        self.assertEqual(hs.day_ends_at, 2)
