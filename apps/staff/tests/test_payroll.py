from datetime import date, datetime, time, timedelta
from decimal import Decimal as D

from django.urls import reverse
from django.utils import timezone

from apps.core.models import HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase
from apps.staff import payroll
from apps.staff.models import EmployeeProfile, PayAdjustment, PayrollMonth, PublicHoliday, TimeEntry

MONTH = date(2026, 9, 1)  # September 2026 starts on a Tuesday


def at(d, h, m=0):
    return timezone.make_aware(datetime.combine(d, time(h, m)))


class PayrollTests(HotelTestCase):
    def work(self, user, d, start, end, brk=0):
        """A shift; `end` may be past midnight (e.g. 26 = 02:00 next day)."""
        out = at(d, 0) + timedelta(hours=end)
        return TimeEntry.objects.create(user=user, clock_in=at(d, start), clock_out=out, break_minutes=brk)

    def profile(self, user, **kw):
        return EmployeeProfile.objects.update_or_create(user=user, defaults=kw)[0]

    def row(self, user, month=MONTH):
        return next(r for r in payroll.calculate(month) if r["user"] == user)

    def test_hourly_pay_and_breaks(self):
        self.profile(self.waiter, pay_type="hourly", pay_rate=D("300"))
        self.work(self.waiter, date(2026, 9, 8), 9, 17, brk=30)  # 7.5 h
        r = self.row(self.waiter)
        self.assertEqual(r["hours"], D("7.50"))
        self.assertEqual(r["base"], D("2250.00"))
        self.assertEqual(r["gross"], D("2250.00"))

    def test_overtime_over_the_contract_week(self):
        self.profile(self.waiter, pay_type="hourly", pay_rate=D("100"), weekly_hours=D("40"))
        for i in range(5):  # Mon 7 – Fri 11 Sept: 5 × 9 h = 45 h
            self.work(self.waiter, date(2026, 9, 7) + timedelta(days=i), 8, 17)
        r = self.row(self.waiter)
        self.assertEqual(r["overtime_hours"], D("5.00"))
        self.assertEqual(r["extras"]["overtime"], D("125.00"))  # 5 h × 100 × 25%
        self.assertEqual(r["gross"], D("4625.00"))

    def test_night_hours_after_22(self):
        self.profile(self.waiter, pay_type="hourly", pay_rate=D("100"))
        self.work(self.waiter, date(2026, 9, 12), 18, 26)  # 18:00–02:00: 4 night hours
        r = self.row(self.waiter)
        self.assertEqual(r["night_hours"], D("4.00"))
        self.assertEqual(r["extras"]["night"], D("80.00"))  # 4 × 100 × 20%

    def test_public_holiday(self):
        PublicHoliday.objects.create(date=date(2026, 9, 5), name="Mother Teresa Day")
        self.profile(self.waiter, pay_type="hourly", pay_rate=D("100"))
        self.work(self.waiter, date(2026, 9, 5), 10, 16)
        hs = HotelSettings.load()
        hs.payroll_holiday_percent = 50
        hs.save()
        r = self.row(self.waiter)
        self.assertEqual(r["holiday_hours"], D("6.00"))
        self.assertEqual(r["extras"]["holiday"], D("300.00"))

    def test_monthly_salary_prorated_with_overtime(self):
        self.profile(self.cleaner, pay_type="monthly", pay_rate=D("60000"), weekly_hours=D("40"), start_date=date(2026, 9, 16))
        r = self.row(self.cleaner)
        self.assertEqual(r["base"], D("30000.00"))  # 15 of 30 days
        for i in range(5):  # Mon 21 – Fri 25: 44 h
            self.work(self.cleaner, date(2026, 9, 21) + timedelta(days=i), 8, 16, brk=0)
        self.work(self.cleaner, date(2026, 9, 26), 8, 12)
        r = self.row(self.cleaner)
        hourly = D("60000") / (D(40) * D(52) / D(12))
        self.assertEqual(r["overtime_hours"], D("4.00"))
        self.assertEqual(r["extras"]["overtime"], (D(4) * hourly * D("1.25")).quantize(D("0.01")))

    def test_week_across_two_months(self):
        self.profile(self.waiter, pay_type="hourly", pay_rate=D("100"), weekly_hours=D("20"))
        self.work(self.waiter, date(2026, 8, 31), 8, 20)  # Monday 31 Aug: 12 h (August)
        self.work(self.waiter, date(2026, 9, 1), 8, 20)  # Tuesday 1 Sept: 12 h → 4 h overtime in September
        self.assertEqual(self.row(self.waiter)["overtime_hours"], D("4.00"))

    def test_adjustments_and_missing_pay(self):
        PayAdjustment.objects.create(user=self.waiter, month=MONTH, amount=D("-5000"), note="Advance")
        self.work(self.reception, date(2026, 9, 8), 9, 17)
        rows = {r["user"]: r for r in payroll.calculate(MONTH)}
        self.assertTrue(rows[self.reception]["missing_pay"])
        self.assertEqual(rows[self.waiter]["adjustments_total"], D("-5000"))

    def test_easter_dates(self):
        self.assertEqual(payroll.western_easter(2026), date(2026, 4, 5))
        self.assertEqual(payroll.orthodox_easter(2026), date(2026, 4, 12))
        self.assertEqual(payroll.western_easter(2027), date(2027, 3, 28))
        self.assertEqual(payroll.orthodox_easter(2027), date(2027, 5, 2))
        self.assertEqual(payroll.add_albanian_holidays(2027), 12)
        self.assertEqual(payroll.add_albanian_holidays(2027), 0)

    def test_pages_approve_and_reopen(self):
        self.profile(self.waiter, pay_type="hourly", pay_rate=D("300"))
        e = self.work(self.waiter, date(2026, 9, 8), 9, 17)
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.get(reverse("staff:payroll") + "?month=2026-09")
        self.assertEqual(r.context["totals"]["gross"], D("2400.00"))
        self.client.post(reverse("staff:payroll_adjustment"), {"month": "2026-09", "user": self.waiter.pk, "amount": "500", "note": "Bonus"})
        self.client.post(reverse("staff:payroll_approve"), {"month": "2026-09"})
        self.assertTrue(PayrollMonth.objects.filter(month=MONTH).exists())
        TimeEntry.objects.filter(pk=e.pk).update(clock_out=at(date(2026, 9, 8), 20))  # changed afterwards
        r = self.client.get(reverse("staff:payroll") + "?month=2026-09")
        self.assertEqual(r.context["totals"]["gross"], D("2900.00"))  # the approved numbers stay
        self.assertEqual(self.client.get(reverse("staff:payroll") + "?month=2026-09&format=xlsx").status_code, 200)
        self.client.post(reverse("staff:payroll_approve"), {"month": "2026-09", "reopen": "1"})
        r = self.client.get(reverse("staff:payroll") + "?month=2026-09")
        self.assertEqual(r.context["totals"]["gross"], D("3800.00"))  # 11 h × 300 + 500

    def test_only_managers(self):
        self.client.login(username="desk", password=PASSWORD)
        self.assertNotEqual(self.client.get(reverse("staff:payroll")).status_code, 200)

    def test_holidays_page(self):
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("staff:holidays") + "?year=2027", {"fill": "1"})
        self.assertEqual(PublicHoliday.objects.filter(date__year=2027).count(), 12)
        self.client.post(reverse("staff:holidays"), {"date": "2027-03-10", "name": "Bajram"})
        self.assertTrue(PublicHoliday.objects.filter(name="Bajram").exists())
