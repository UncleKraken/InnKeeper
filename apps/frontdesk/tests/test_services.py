from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.core.exceptions import BusinessError
from apps.core.testing import HotelTestCase
from apps.finance.models import Charge
from apps.frontdesk import services
from apps.frontdesk.models import Reservation, Room
from apps.housekeeping.models import HousekeepingTask


class ReservationRulesTests(HotelTestCase):
    def test_creating_a_reservation_opens_a_folio(self):
        res = self.make_reservation()
        self.assertEqual(res.folio.balance, Decimal("0"))
        self.assertEqual(res.code, f"R{res.pk:06d}")

    def test_double_booking_the_same_room_is_refused(self):
        self.make_reservation(start=0, nights=3)
        with self.assertRaises(ValidationError) as ctx:
            self.make_reservation(start=2, nights=2)
        self.assertIn("room", ctx.exception.message_dict)

    def test_back_to_back_stays_are_allowed(self):
        self.make_reservation(start=0, nights=2)
        second = self.make_reservation(start=2, nights=2)  # arrives the day the first leaves
        self.assertTrue(second.pk)

    def test_cancelled_stays_free_the_room(self):
        first = self.make_reservation(start=0, nights=3)
        services.cancel(first, self.reception)
        self.assertTrue(self.make_reservation(start=1, nights=1).pk)

    def test_capacity_is_enforced(self):
        res = Reservation(
            guest=self.guest,
            room=self.room,
            arrival=self.today,
            departure=self.today + timedelta(days=1),
            adults=3,
            rate=Decimal("80"),
        )
        with self.assertRaises(ValidationError):
            services.save_reservation(res, self.reception)

    def test_departure_must_follow_arrival(self):
        res = Reservation(
            guest=self.guest, room=self.room, arrival=self.today, departure=self.today, adults=1, rate=Decimal("80")
        )
        with self.assertRaises(ValidationError):
            services.save_reservation(res, self.reception)


class CheckInOutTests(HotelTestCase):
    def test_check_in_today(self):
        res = services.check_in(self.make_reservation(), self.reception)
        self.assertEqual(res.status, Reservation.Status.CHECKED_IN)
        self.assertIsNotNone(res.checked_in_at)

    def test_cannot_check_in_a_future_arrival(self):
        with self.assertRaises(BusinessError):
            services.check_in(self.make_reservation(start=3), self.reception)

    def test_cannot_check_in_to_out_of_order_room(self):
        res = self.make_reservation()
        Room.objects.filter(pk=self.room.pk).update(out_of_order=True)
        with self.assertRaises(BusinessError):
            services.check_in(res, self.reception)

    def test_check_out_requires_a_settled_bill(self):
        res = self.make_reservation(start=-2, nights=2, status=Reservation.Status.CHECKED_IN)
        with self.assertRaises(BusinessError):
            services.check_out(res, self.reception)
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.CHECKED_IN)
        # Room nights were posted while trying, and posting again adds nothing.
        self.assertEqual(res.folio.balance, Decimal("160.00"))
        services.post_accommodation(res, self.reception)
        self.assertEqual(res.folio.balance, Decimal("160.00"))

    def test_full_check_out_flow(self):
        res = self.make_reservation(start=-2, nights=2, status=Reservation.Status.CHECKED_IN)
        services.post_accommodation(res, self.reception)
        services.add_payment(res.folio, amount=Decimal("160.00"), method="card", user=self.reception)
        services.check_out(res, self.reception)
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.CHECKED_OUT)
        self.assertEqual(res.folio.status, "closed")
        self.room.refresh_from_db()
        self.assertEqual(self.room.hk_status, Room.HKStatus.DIRTY)
        self.assertTrue(HousekeepingTask.objects.filter(room=self.room, kind="departure", status="pending").exists())

    def test_early_departure_charges_only_nights_stayed(self):
        res = self.make_reservation(start=-1, nights=4, status=Reservation.Status.CHECKED_IN)
        services.post_accommodation(res, self.reception)
        self.assertEqual(res.folio.accommodation_nights_posted(), 1)
        services.add_payment(res.folio, amount=Decimal("80.00"), method="cash", user=self.reception)
        services.check_out(res, self.reception)
        res.refresh_from_db()
        self.assertEqual(res.departure, self.today)

    def test_manager_can_check_out_with_open_balance(self):
        res = self.make_reservation(start=-1, nights=1, status=Reservation.Status.CHECKED_IN)
        services.check_out(res, self.manager, allow_balance=True)
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.CHECKED_OUT)
        self.assertEqual(res.folio.status, "open")  # stays on the unpaid list
        services.add_payment(res.folio, amount=Decimal("80.00"), method="bank_transfer", user=self.accountant)
        res.folio.refresh_from_db()
        self.assertEqual(res.folio.status, "closed")


class NightAuditTests(HotelTestCase):
    def test_night_audit_posts_last_night_once(self):
        res = self.make_reservation(start=-1, nights=3, status=Reservation.Status.CHECKED_IN)
        self.assertEqual(services.night_audit(), 1)
        self.assertEqual(services.night_audit(), 0)
        charge = Charge.objects.get(folio=res.folio)
        self.assertEqual(charge.quantity, 1)
        self.assertEqual(charge.business_date, self.today - timedelta(days=1))

    def test_night_audit_on_arrival_day_posts_nothing(self):
        self.make_reservation(start=0, nights=2, status=Reservation.Status.CHECKED_IN)
        self.assertEqual(services.night_audit(), 0)


class LedgerTests(HotelTestCase):
    def test_only_managers_can_void(self):
        res = self.make_reservation()
        charge = services.add_charge(
            res.folio, description="Parking", quantity=2, unit_price=Decimal("5"), user=self.reception
        )
        self.assertEqual(charge.amount, Decimal("10.00"))
        with self.assertRaises(BusinessError):
            services.void_entry(charge, reason="mistake", user=self.reception)
        with self.assertRaises(BusinessError):
            services.void_entry(charge, reason=" ", user=self.manager)
        services.void_entry(charge, reason="Guest had no car", user=self.manager)
        self.assertEqual(res.folio.balance, Decimal("0"))
        self.assertTrue(Charge.objects.filter(pk=charge.pk).exists(), "voided entries are kept, never deleted")

    def test_refunds_reduce_payments(self):
        res = self.make_reservation()
        services.add_payment(res.folio, amount=Decimal("50"), method="cash", user=self.reception)
        services.add_payment(res.folio, amount=Decimal("-20"), method="cash", user=self.reception)
        self.assertEqual(res.folio.balance, Decimal("-30"))
