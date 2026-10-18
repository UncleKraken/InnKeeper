from datetime import date
from decimal import Decimal as D

from django.urls import reverse

from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Expense
from apps.finance.monthly import month_bounds, report
from apps.outlets import services as pos


class MonthlyReportTests(HotelTestCase):
    def setUp(self):
        HotelSettings.objects.update(vat_rate=D("20"), vat_rate_accommodation=D("6"), tax_status="vat")
        clear_settings_cache()
        o = pos.open_order(self.restaurant, user=self.waiter, table=self.table)
        pos.add_item(o, self.dish, user=self.waiter, quantity=2)  # 22.00
        pos.pay_order(o, method="card", user=self.waiter)
        Expense.objects.create(category="rent", description="Rent", amount=D("5"), method="cash", created_by=self.manager)

    def test_bounds(self):
        self.assertEqual(month_bounds("2026-02"), (date(2026, 2, 1), date(2026, 2, 28)))

    def test_numbers(self):
        start, end = month_bounds(self.today.strftime("%Y-%m"))
        r = report(start, end)
        self.assertEqual((r["revenue"], r["received"], r["expenses_total"], r["profit"]), (D("22.00"), D("22.00"), D("5"), D("17.00")))
        self.assertEqual(r["vat_rows"][0]["vat"], D("3.67"))
        self.assertEqual(len(r["days"]), (end - start).days + 1)
        self.assertEqual(r["bill_count"], 1)
        self.assertEqual(r["days_not_closed"], 1)

    def test_page_and_excel(self):
        self.client.login(username="money", password=PASSWORD)
        m = self.today.strftime("%Y-%m")
        page = self.client.get(reverse("finance:monthly") + f"?month={m}")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "22.00")
        r = self.client.get(reverse("finance:monthly") + f"?month={m}&format=xlsx")
        self.assertTrue(r.content.startswith(b"PK"))
        self.assertEqual(self.client.get(reverse("finance:monthly") + "?month=bad").status_code, 200)
