from datetime import timedelta
from decimal import Decimal

from django.urls import reverse

from apps.core.exceptions import BusinessError
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Folio
from apps.frontdesk import services
from apps.frontdesk.groups import create_group, group_check_out
from apps.frontdesk.models import Group, Reservation, Room


class GroupTests(HotelTestCase):
    def make_group(self, **kw):
        defaults = dict(
            name="Wedding",
            contact=self.guest,
            rooms=[self.room, self.room2],
            arrival=self.today,
            departure=self.today + timedelta(days=2),
            adults=2,
            user=self.reception,
        )
        defaults.update(kw)
        return create_group(**defaults)

    def test_create_books_every_room_with_the_first_as_main(self):
        group = self.make_group()
        self.assertEqual(group.reservations.count(), 2)
        self.assertEqual(group.master.room, self.room)
        self.assertTrue(all(r.rate == Decimal("80.00") for r in group.reservations.all()))

    def test_one_taken_room_books_nothing(self):
        self.make_reservation(room=self.room2, start=1, nights=1)
        with self.assertRaises(BusinessError):
            self.make_group()
        self.assertFalse(Group.objects.exists())
        self.assertEqual(Reservation.objects.count(), 1)

    def test_group_rate_overrides_price_list(self):
        group = self.make_group(rate=Decimal("60"))
        self.assertEqual({r.rate for r in group.reservations.all()}, {Decimal("60")})

    def test_shared_bill_collects_other_rooms_at_check_out(self):
        group = self.make_group()
        main, other = group.master, group.reservations.exclude(pk=group.master_id).get()
        for r in (main, other):
            services.check_in(r, self.reception)
        services.add_charge(
            other.folio, description="Minibar", quantity=1, unit_price=Decimal("7"), user=self.reception
        )
        group_check_out(other, self.reception)  # the other room leaves without paying
        other.refresh_from_db()
        self.assertEqual(other.status, Reservation.Status.CHECKED_OUT)
        self.assertEqual(other.folio.balance, Decimal("0"))
        self.assertEqual(other.folio.status, Folio.Status.CLOSED)
        main.folio.refresh_from_db()
        self.assertEqual(main.folio.balance, Decimal("87.00"))  # 1 night + minibar of the other room
        with self.assertRaises(BusinessError):
            group_check_out(main, self.reception)  # the payer must settle
        services.add_payment(main.folio, amount=Decimal("200"), method="card", user=self.reception)
        group_check_out(main, self.reception)
        main.refresh_from_db()
        self.assertEqual(main.status, Reservation.Status.CHECKED_OUT)

    def test_each_room_pays_when_one_bill_is_off(self):
        group = self.make_group(one_bill=False)
        other = group.reservations.exclude(pk=group.master_id).get()
        services.check_in(other, self.reception)
        with self.assertRaises(BusinessError):
            group_check_out(other, self.reception)

    def test_pages_and_bulk_actions(self):
        self.client.login(username="desk", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("frontdesk:group_create")).status_code, 200)
        data = {
            "name": "Tour Italy",
            "contact_first": "Marco",
            "contact_last": "Bianchi",
            "arrival": self.today.isoformat(),
            "departure": (self.today + timedelta(days=1)).isoformat(),
            "adults": 2,
            "source": "agency",
            "one_bill": "on",
        }
        r = self.client.post(reverse("frontdesk:group_create"), {**data, "action": "search"})
        self.assertContains(r, 'name="rooms"')
        r = self.client.post(
            reverse("frontdesk:group_create"), {**data, "action": "save", "rooms": [self.room.pk, self.room2.pk]}
        )
        group = Group.objects.get(name="Tour Italy")
        self.assertRedirects(r, reverse("frontdesk:group_detail", args=[group.pk]))
        self.assertEqual(self.client.get(reverse("frontdesk:group_detail", args=[group.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("frontdesk:group_list")).status_code, 200)
        self.client.post(reverse("frontdesk:group_action", args=[group.pk]), {"action": "check_in"})
        self.assertEqual(group.reservations.filter(status="checked_in").count(), 2)
        self.client.post(reverse("frontdesk:group_action", args=[group.pk]), {"action": "move_bills"})
        self.assertEqual(group.master.folio.balance, Decimal("0"))  # nothing posted yet
        # The single check-out button also understands groups.
        other = group.reservations.exclude(pk=group.master_id).get()
        self.client.post(reverse("frontdesk:check_out", args=[other.pk]))
        other.refresh_from_db()
        self.assertEqual(other.status, Reservation.Status.CHECKED_OUT)
        self.assertEqual(Room.objects.get(pk=other.room_id).hk_status, Room.HKStatus.DIRTY)

    def test_cancel_group(self):
        group = self.make_group(arrival=self.today + timedelta(days=5), departure=self.today + timedelta(days=6))
        self.client.login(username="desk", password=PASSWORD)
        self.client.post(reverse("frontdesk:group_action", args=[group.pk]), {"action": "cancel"})
        self.assertEqual(group.reservations.filter(status="cancelled").count(), 2)
