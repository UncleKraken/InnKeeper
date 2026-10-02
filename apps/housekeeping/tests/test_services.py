from apps.core.testing import HotelTestCase
from apps.frontdesk.models import Room
from apps.housekeeping import services
from apps.housekeeping.models import HousekeepingTask, MaintenanceTicket


class HousekeepingTests(HotelTestCase):
    def test_finishing_a_cleaning_task_makes_the_room_clean(self):
        task = services.room_vacated(self.room, self.reception)
        services.advance_task(task, self.cleaner)
        task.refresh_from_db()
        self.assertEqual(task.status, HousekeepingTask.Status.IN_PROGRESS)
        self.assertEqual(task.assigned_to, self.cleaner)
        services.advance_task(task, self.cleaner)
        self.room.refresh_from_db()
        self.assertEqual(self.room.hk_status, Room.HKStatus.CLEAN)

    def test_marking_room_clean_closes_open_tasks(self):
        task = services.room_vacated(self.room, self.reception)
        services.set_room_status(self.room, Room.HKStatus.CLEAN, self.cleaner)
        task.refresh_from_db()
        self.assertEqual(task.status, HousekeepingTask.Status.DONE)


class MaintenanceTests(HotelTestCase):
    def test_blocking_ticket_takes_room_out_of_order_until_resolved(self):
        ticket = services.save_ticket(
            MaintenanceTicket(title="AC broken", room=self.room, blocks_room=True), self.cleaner
        )
        self.room.refresh_from_db()
        self.assertTrue(self.room.out_of_order)
        services.resolve_ticket(ticket, self.manager, "Replaced filter")
        self.room.refresh_from_db()
        self.assertFalse(self.room.out_of_order)
        self.assertEqual(self.room.hk_status, Room.HKStatus.DIRTY)
