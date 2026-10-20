from datetime import date, time, timedelta

from django.urls import reverse

from apps.core.exceptions import BusinessError
from apps.core.testing import PASSWORD, HotelTestCase
from apps.staff import requests as svc
from apps.staff import services
from apps.staff.models import EmployeeProfile, LeaveRequest, PublicHoliday, ScheduledShift, SwapRequest


class LeaveTests(HotelTestCase):
    def test_ask_approve_balance_and_schedule(self):
        EmployeeProfile.objects.create(user=self.waiter, leave_days=22)
        PublicHoliday.objects.create(date=date(2027, 5, 3), name="Holiday")
        self.client.login(username="waiter", password=PASSWORD)
        self.client.post(reverse("staff:leave_ask"), {"kind": "annual", "start": "2027-05-03", "end": "2027-05-09", "note": "Wedding"})
        req = LeaveRequest.objects.get()
        self.assertEqual(req.working_days(), 4)  # Mon is a holiday, weekend not counted
        self.assertEqual(svc.balance(self.waiter, 2027)["waiting"], 4)
        # Overlapping request is refused.
        with self.assertRaises(BusinessError):
            svc.ask_leave(self.waiter, kind="annual", start=date(2027, 5, 5), end=date(2027, 5, 6))
        self.client.login(username="boss", password=PASSWORD)
        self.assertContains(self.client.get("/"), reverse("staff:requests"))  # nav shows waiting requests
        self.assertContains(self.client.get(reverse("staff:requests")), "Wedding")
        self.client.post(reverse("staff:leave_decide", args=[req.pk]), {"approve": "1"})
        req.refresh_from_db()
        self.assertEqual(req.status, "approved")
        self.assertEqual(svc.balance(self.waiter, 2027), {"year": 2027, "allowance": 22, "taken": 4, "waiting": 0, "left": 18})
        r = self.client.get(reverse("staff:schedule") + "?week=2027-05-03")
        self.assertContains(r, "sched-leave")

    def test_leave_is_not_a_no_show(self):
        day = self.today - timedelta(days=3)
        ScheduledShift.objects.create(user=self.waiter, date=day, start=time(9), end=time(17))
        rows = services.attendance(day, day)
        self.assertEqual(rows[0]["no_show"], 1)
        LeaveRequest.objects.create(user=self.waiter, kind="sick", start=day, end=day, status="approved")
        self.assertEqual(services.attendance(day, day)[0]["no_show"], 0)

    def test_decline_and_cancel(self):
        req = svc.ask_leave(self.waiter, kind="annual", start=self.today + timedelta(days=10), end=self.today + timedelta(days=11))
        svc.decide_leave(req, self.manager, approve=False, reason="Busy weekend")
        with self.assertRaises(BusinessError):
            svc.decide_leave(req, self.manager, approve=True)
        req2 = svc.ask_leave(self.waiter, kind="annual", start=self.today + timedelta(days=10), end=self.today + timedelta(days=11))
        self.client.login(username="waiter", password=PASSWORD)
        self.client.post(reverse("staff:leave_cancel", args=[req2.pk]))
        req2.refresh_from_db()
        self.assertEqual(req2.status, "cancelled")
        self.assertContains(self.client.get(reverse("staff:my_hours")), "Busy weekend")

    def test_staff_cannot_decide(self):
        req = svc.ask_leave(self.waiter, kind="annual", start=self.today + timedelta(days=5), end=self.today + timedelta(days=5))
        self.client.login(username="waiter", password=PASSWORD)
        self.client.post(reverse("staff:leave_decide", args=[req.pk]), {"approve": "1"})
        req.refresh_from_db()
        self.assertEqual(req.status, "pending")


class SwapTests(HotelTestCase):
    def setUp(self):
        self.shift = ScheduledShift.objects.create(user=self.waiter, date=self.today + timedelta(days=2), start=time(18), end=time(2))

    def test_colleague_agrees_then_manager_approves(self):
        self.client.login(username="waiter", password=PASSWORD)
        self.client.post(reverse("staff:swap_ask"), {"shift": self.shift.pk, "to_user": self.reception.pk, "note": "Exam"})
        swap = SwapRequest.objects.get()
        self.client.login(username="desk", password=PASSWORD)
        r = self.client.get(reverse("staff:my_hours"))
        self.assertContains(r, "Exam")
        self.client.post(reverse("staff:swap_answer", args=[swap.pk]), {"agree": "1"})
        swap.refresh_from_db()
        self.assertEqual(swap.status, "agreed")
        self.shift.refresh_from_db()
        self.assertEqual(self.shift.user, self.waiter)  # not yet: a manager decides
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("staff:swap_decide", args=[swap.pk]), {"approve": "1"})
        self.shift.refresh_from_db()
        self.assertEqual(self.shift.user, self.reception)

    def test_only_own_future_shifts_and_one_open_request(self):
        with self.assertRaises(BusinessError):
            svc.ask_swap(self.shift, self.reception, self.cleaner)
        svc.ask_swap(self.shift, self.waiter, self.cleaner)
        with self.assertRaises(BusinessError):
            svc.ask_swap(self.shift, self.waiter, self.reception)
        past = ScheduledShift.objects.create(user=self.waiter, date=self.today - timedelta(days=1), start=time(9), end=time(17))
        with self.assertRaises(BusinessError):
            svc.ask_swap(past, self.waiter, self.cleaner)

    def test_colleague_refuses_and_others_cannot_answer(self):
        swap = svc.ask_swap(self.shift, self.waiter, self.cleaner)
        with self.assertRaises(BusinessError):
            svc.colleague_answer(swap, self.reception, agree=True)
        svc.colleague_answer(swap, self.cleaner, agree=False)
        swap.refresh_from_db()
        self.assertEqual(swap.status, "declined")
        self.shift.refresh_from_db()
        self.assertEqual(self.shift.user, self.waiter)
