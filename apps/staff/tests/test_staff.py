from datetime import time, timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from apps.core.exceptions import BusinessError
from apps.core.models import AuditLog
from apps.core.testing import PASSWORD, HotelTestCase
from apps.staff import services
from apps.staff.models import EmployeeProfile, Position, ScheduledShift, TimeEntry


class TimeClockTests(HotelTestCase):
    def test_clock_in_and_out(self):
        e = services.clock_in(self.waiter)
        with self.assertRaises(BusinessError):
            services.clock_in(self.waiter)
        later = e.clock_in + timedelta(hours=8, minutes=30)
        e = services.clock_out(self.waiter, when=later)
        self.assertEqual(e.hours, 8.5)
        with self.assertRaises(BusinessError):
            services.clock_out(self.waiter)

    def test_sidebar_button_toggles(self):
        self.client.login(username="waiter", password=PASSWORD)
        page = self.client.get(reverse("staff:my_hours"))
        self.assertContains(page, reverse("staff:clock"))
        self.client.post(reverse("staff:clock"), {"next": "/outlets/"})
        self.assertIsNotNone(services.open_entry(self.waiter))
        self.client.post(reverse("staff:clock"))
        self.assertIsNone(services.open_entry(self.waiter))
        self.assertEqual(TimeEntry.objects.filter(user=self.waiter).count(), 1)

    def test_pin_pad_clock_mode_does_not_sign_in(self):
        self.waiter.set_pin("4826")
        self.waiter.save()
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("accounts:shared_till"), {"on": "1"})
        self.client.post(reverse("accounts:lock"))
        r = self.client.post(reverse("accounts:pin_pad"), {"user": self.waiter.pk, "pin": "4826", "action": "clock"})
        self.assertContains(r, "id=\"pin-done\"")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(TimeEntry.objects.get(user=self.waiter).source, "pin")
        r = self.client.post(reverse("accounts:pin_pad"), {"user": self.waiter.pk, "pin": "0000", "action": "clock"})
        self.assertIsNotNone(services.open_entry(self.waiter))  # wrong PIN changes nothing


class ScheduleAndAttendanceTests(HotelTestCase):
    def setUp(self):
        self.bar = Position.objects.create(name="Bartender", color="amber")
        EmployeeProfile.objects.create(user=self.waiter, position=self.bar)
        self.client.login(username="boss", password=PASSWORD)

    def test_overnight_shift_hours(self):
        s = ScheduledShift(user=self.waiter, date=self.today, start=time(18), end=time(2))
        self.assertEqual(s.hours, 8)

    def test_late_no_show_and_report(self):
        day = self.today - timedelta(days=1)
        ScheduledShift.objects.create(user=self.waiter, date=day, start=time(8), end=time(16), position=self.bar)
        ScheduledShift.objects.create(user=self.waiter, date=day - timedelta(days=1), start=time(8), end=time(16))
        start = timezone.make_aware(timezone.datetime.combine(day, time(8, 25)))
        TimeEntry.objects.create(user=self.waiter, clock_in=start, clock_out=start + timedelta(hours=7, minutes=35))
        row = services.attendance(day - timedelta(days=1), day)[0]
        self.assertEqual((row["late"], row["no_show"], row["planned"], str(row["worked"])), (1, 1, 16, "7.58"))
        page = self.client.get(reverse("staff:attendance") + f"?from={day - timedelta(days=1)}&to={day}")
        self.assertRegex(page.content.decode(), r"7[.,]58")
        x = self.client.get(reverse("staff:attendance") + f"?from={day}&to={day}&format=xlsx")
        self.assertTrue(x.content.startswith(b"PK"))

    def test_schedule_page_add_copy_and_staff_see_their_shifts(self):
        week = self.today - timedelta(days=self.today.weekday())
        r = self.client.post(reverse("staff:shift_create"), {"user": self.waiter.pk, "date": week.isoformat(), "start": "17:00", "end": "01:00", "position": self.bar.pk, "note": ""})
        self.assertEqual(r.status_code, 302)
        page = self.client.get(reverse("staff:schedule") + f"?week={week}")
        self.assertContains(page, "17:00–01:00")
        nxt = week + timedelta(days=7)
        self.client.post(reverse("staff:copy_week"), {"week": nxt.isoformat()})
        self.assertTrue(ScheduledShift.objects.filter(date=nxt).exists())
        self.client.post(reverse("staff:copy_week"), {"week": nxt.isoformat()})
        self.assertEqual(ScheduledShift.objects.filter(date=nxt).count(), 1)  # not twice
        self.client.login(username="waiter", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("staff:schedule")).status_code, 403)
        self.assertContains(self.client.get(reverse("staff:my_hours")), "17:00–01:00")

    def test_manager_corrects_hours_with_a_reason(self):
        e = services.clock_in(self.waiter)
        url = reverse("staff:entry_edit", args=[e.pk])
        out = timezone.localtime(e.clock_in + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(url, {"clock_in": timezone.localtime(e.clock_in).strftime("%Y-%m-%dT%H:%M"), "clock_out": out, "break_minutes": 30, "note": "", "edit_reason": ""})
        self.assertEqual(r.status_code, 200)  # reason required
        r = self.client.post(url, {"clock_in": timezone.localtime(e.clock_in).strftime("%Y-%m-%dT%H:%M"), "clock_out": out, "break_minutes": 30, "note": "", "edit_reason": "forgot to clock out"})
        self.assertEqual(r.status_code, 302)
        e.refresh_from_db()
        self.assertEqual((e.edited_by, e.break_minutes), (self.manager, 30))
        self.assertTrue(AuditLog.objects.filter(action="staff.entry_edit").exists())

    def test_profile_is_for_managers_only(self):
        url = reverse("staff:profile", args=[self.waiter.pk])
        r = self.client.post(url, {"position": self.bar.pk, "employment": "seasonal", "personal_id": "J12345678A", "pay_type": "hourly", "pay_rate": "350", "notes": ""})
        self.assertEqual(r.status_code, 302)
        self.waiter.employee.refresh_from_db()
        self.assertEqual(self.waiter.employee.personal_id, "J12345678A")
        self.assertNotIn("J12345678A", AuditLog.objects.latest("created_at").description)
        self.assertContains(self.client.get(reverse("accounts:staff_list")), "Bartender")
        self.client.login(username="waiter", password=PASSWORD)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_manager_clocks_someone_in(self):
        self.client.post(reverse("staff:clock_for", args=[self.cleaner.pk]))
        self.assertEqual(services.open_entry(self.cleaner).source, "manual")
        page = self.client.get(reverse("staff:attendance"))
        self.assertContains(page, str(self.cleaner))

    def test_forgotten_clock_out_flag(self):
        with mock.patch("django.utils.timezone.now", return_value=timezone.now() - timedelta(hours=20)):
            services.clock_in(self.waiter)
        self.assertTrue(services.open_entry(self.waiter).forgotten)
