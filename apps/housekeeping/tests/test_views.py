"""The housekeeping and maintenance pages, as cleaners, reception and managers use them on their phones."""

from django.urls import reverse

from apps.core.testing import PASSWORD, HotelTestCase
from apps.frontdesk.models import Room
from apps.housekeeping.models import HousekeepingTask, MaintenanceTicket


class BoardTests(HotelTestCase):
    def setUp(self):
        Room.objects.filter(pk=self.room.pk).update(hk_status=Room.HKStatus.DIRTY)

    def test_cleaner_starts_on_dirty_rooms_others_see_all(self):
        self.client.login(username="cleaner", password=PASSWORD)
        r = self.client.get(reverse("housekeeping:board"))
        self.assertEqual(r.context["show"], "dirty")
        rooms = [x["room"].number for _, items in r.context["floors"] for x in items]
        self.assertEqual(rooms, ["101"])
        self.client.login(username="desk", password=PASSWORD)
        r = self.client.get(reverse("housekeeping:board"))
        rooms = [x["room"].number for _, items in r.context["floors"] for x in items]
        self.assertEqual(sorted(rooms), ["101", "102"])
        self.assertEqual(r.context["counts"]["dirty"], 1)

    def test_waiter_and_accountant_cannot_open_it(self):
        for name in ("waiter", "money"):
            self.client.login(username=name, password=PASSWORD)
            self.assertIn(self.client.get(reverse("housekeeping:board")).status_code, (302, 403))

    def test_mark_room_clean_closes_its_cleaning_task(self):
        task = HousekeepingTask.objects.create(room=self.room, kind=HousekeepingTask.Kind.DEPARTURE)
        self.client.login(username="cleaner", password=PASSWORD)
        r = self.client.post(reverse("housekeeping:room_status", args=[self.room.pk]), {"status": "clean"})
        self.assertRedirects(r, reverse("housekeeping:board"), fetch_redirect_response=False)
        self.room.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(self.room.hk_status, Room.HKStatus.CLEAN)
        self.assertEqual(task.status, HousekeepingTask.Status.DONE)
        self.assertEqual(task.completed_by.username, "cleaner")

    def test_unknown_status_is_refused_politely(self):
        self.client.login(username="cleaner", password=PASSWORD)
        r = self.client.post(reverse("housekeeping:room_status", args=[self.room.pk]), {"status": "sparkling"}, follow=True)
        self.room.refresh_from_db()
        self.assertEqual(self.room.hk_status, Room.HKStatus.DIRTY)
        self.assertContains(r, "alert")

    def test_get_is_not_allowed_for_changes(self):
        self.client.login(username="cleaner", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("housekeeping:room_status", args=[self.room.pk])).status_code, 405)


class TaskTests(HotelTestCase):
    def test_add_start_and_finish_a_task(self):
        self.client.login(username="desk", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("housekeeping:task_create") + f"?room={self.room.pk}").status_code, 200)
        r = self.client.post(
            reverse("housekeeping:task_create"),
            {"room": self.room.pk, "kind": "deep", "due_date": self.today.isoformat(), "notes": "Curtains"},
        )
        self.assertRedirects(r, reverse("housekeeping:board"), fetch_redirect_response=False)
        task = HousekeepingTask.objects.get(notes="Curtains")
        self.assertEqual(task.created_by.username, "desk")

        self.client.login(username="cleaner", password=PASSWORD)
        self.client.post(reverse("housekeeping:task_advance", args=[task.pk]))
        task.refresh_from_db()
        self.assertEqual(task.status, HousekeepingTask.Status.IN_PROGRESS)
        self.assertEqual(task.assigned_to.username, "cleaner")
        self.client.post(reverse("housekeeping:task_advance", args=[task.pk]))
        task.refresh_from_db()
        self.assertEqual(task.status, HousekeepingTask.Status.DONE)

    def test_assign_only_to_active_staff(self):
        task = HousekeepingTask.objects.create(room=self.room)
        self.client.login(username="desk", password=PASSWORD)
        self.client.post(reverse("housekeeping:task_assign", args=[task.pk]), {"assigned_to": self.cleaner.pk})
        task.refresh_from_db()
        self.assertEqual(task.assigned_to, self.cleaner)
        self.cleaner.is_active = False
        self.cleaner.save()
        self.client.post(reverse("housekeeping:task_assign", args=[task.pk]), {"assigned_to": self.cleaner.pk})
        task.refresh_from_db()
        self.assertIsNone(task.assigned_to)

    def test_cleaner_sees_own_and_unassigned_tasks(self):
        mine = HousekeepingTask.objects.create(room=self.room, assigned_to=self.cleaner)
        free = HousekeepingTask.objects.create(room=self.room2)
        other = HousekeepingTask.objects.create(room=self.room2, assigned_to=self.reception, notes="other")
        self.client.login(username="cleaner", password=PASSWORD)
        tasks = set(self.client.get(reverse("housekeeping:board")).context["tasks"])
        self.assertEqual(tasks, {mine, free})
        tasks = set(self.client.get(reverse("housekeeping:board") + "?mine=0").context["tasks"])
        self.assertIn(other, tasks)


class MaintenanceTests(HotelTestCase):
    def test_report_blocking_problem_then_resolve(self):
        self.client.login(username="cleaner", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("housekeeping:ticket_create") + f"?room={self.room.pk}").status_code, 200)
        r = self.client.post(
            reverse("housekeeping:ticket_create"),
            {"title": "Shower leaking", "room": self.room.pk, "priority": "high", "blocks_room": "on", "description": ""},
        )
        self.assertRedirects(r, reverse("housekeeping:ticket_list"), fetch_redirect_response=False)
        ticket = MaintenanceTicket.objects.get(title="Shower leaking")
        self.room.refresh_from_db()
        self.assertTrue(self.room.out_of_order)
        self.assertEqual(ticket.reported_by.username, "cleaner")

        self.assertContains(self.client.get(reverse("housekeeping:ticket_list")), "Shower leaking")
        self.client.post(reverse("housekeeping:ticket_status", args=[ticket.pk]), {"action": "start"})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, MaintenanceTicket.Status.IN_PROGRESS)
        self.assertEqual(ticket.assigned_to.username, "cleaner")

        self.client.post(reverse("housekeeping:ticket_status", args=[ticket.pk]), {"action": "resolve", "resolution": "New seal"})
        ticket.refresh_from_db()
        self.room.refresh_from_db()
        self.assertEqual(ticket.status, MaintenanceTicket.Status.RESOLVED)
        self.assertFalse(self.room.out_of_order)
        self.assertContains(self.client.get(reverse("housekeeping:ticket_list") + "?show=resolved"), "Shower leaking")

        r = self.client.post(reverse("housekeeping:ticket_status", args=[ticket.pk]), {"action": "resolve"}, follow=True)
        self.assertContains(r, "alert")  # already resolved

    def test_blocking_without_room_is_refused(self):
        self.client.login(username="desk", password=PASSWORD)
        r = self.client.post(
            reverse("housekeeping:ticket_create"),
            {"title": "Lift stuck", "location": "Lift", "priority": "normal", "blocks_room": "on"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(MaintenanceTicket.objects.filter(title="Lift stuck").exists())

    def test_edit_ticket_and_filter_mine(self):
        ticket = MaintenanceTicket.objects.create(title="Lamp", room=self.room, assigned_to=self.cleaner)
        self.client.login(username="cleaner", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("housekeeping:ticket_edit", args=[ticket.pk])).status_code, 200)
        r = self.client.get(reverse("housekeeping:ticket_list") + "?mine=1")
        self.assertEqual([t.title for t in r.context["object_list"]], ["Lamp"])
