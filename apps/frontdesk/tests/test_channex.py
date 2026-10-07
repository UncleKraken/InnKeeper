from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.urls import reverse

from apps.core.models import HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase
from apps.frontdesk import channex
from apps.frontdesk.models import ChannelBooking, ChannelSyncState, Reservation, SeasonRate

D = Decimal


class FakeClient:
    def __init__(self, revisions=None):
        self.revisions = list(revisions or [])
        self.sent_availability, self.sent_restrictions, self.acked = [], [], []

    def availability(self, values):
        self.sent_availability += values
        return {}

    def restrictions(self, values):
        self.sent_restrictions += values
        return {}

    def feed(self, property_id):
        out, self.revisions = self.revisions, []
        return out

    def ack(self, revision_id):
        self.acked.append(revision_id)

    def room_types(self, property_id):
        return [{"id": "cx-dbl", "title": "Double"}]

    def rate_plans(self, property_id):
        return [{"id": "cx-dbl-bar", "title": "Best rate", "currency": "EUR"}]


def revision(rid, status="new", booking="bk-1", rooms=None, arrival=None, departure=None, **extra):
    return {
        "id": rid,
        "booking_id": booking,
        "status": status,
        "ota_name": "Booking.com",
        "ota_reservation_code": "998877",
        "arrival_date": arrival.isoformat(),
        "departure_date": departure.isoformat(),
        "amount": "190.00",
        "currency": "EUR",
        "customer": {"name": "Lena", "surname": "Weber", "mail": "lena@example.com", "phone": "+49 1", "country": "DE"},
        "rooms": rooms
        if rooms is not None
        else [
            {
                "room_type_id": "cx-dbl",
                "rate_plan_id": "cx-dbl-bar",
                "checkin_date": arrival.isoformat(),
                "checkout_date": departure.isoformat(),
                "occupancy": {"adults": 2, "children": 0, "infants": 0},
                "days": {
                    (arrival + timedelta(days=i)).isoformat(): ("90.00" if i == 0 else "100.00")
                    for i in range((departure - arrival).days)
                },
                "amount": "190.00",
            }
        ],
        "notes": "Late arrival",
        "payment_collect": "ota",
        **extra,
    }


class ChannexTests(HotelTestCase):
    def setUp(self):
        hs = HotelSettings.load()
        hs.channex_enabled, hs.channex_api_key, hs.channex_property_id = True, "key", "prop-1"
        hs.channex_days_ahead = 30
        hs.save()
        self.double.channex_room_type_id = "cx-dbl"
        self.double.channex_rate_plan_id = "cx-dbl-bar"
        self.double.save()
        self.a = self.today + timedelta(days=4)
        self.d = self.a + timedelta(days=2)

    def run_with(self, client, fn, *args, **kw):
        with mock.patch.object(channex.Client, "from_settings", return_value=client):
            return fn(*args, **kw)

    # ----- Sending -----

    def test_availability_counts_free_rooms_per_day_in_runs(self):
        self.make_reservation(start=2, nights=3)  # one of the two doubles taken on days 2,3,4
        availability, restrictions = channex.build_ari(days=10)
        runs = [(x["date_from"], x["date_to"], x["availability"]) for x in availability]
        t = self.today
        self.assertEqual(
            runs,
            [
                (t.isoformat(), (t + timedelta(days=1)).isoformat(), 2),
                ((t + timedelta(days=2)).isoformat(), (t + timedelta(days=4)).isoformat(), 1),
                ((t + timedelta(days=5)).isoformat(), (t + timedelta(days=9)).isoformat(), 2),
            ],
        )
        self.assertEqual(availability[0]["property_id"], "prop-1")
        self.assertEqual(
            restrictions,
            [
                {
                    "property_id": "prop-1",
                    "rate_plan_id": "cx-dbl-bar",
                    "date_from": t.isoformat(),
                    "date_to": (t + timedelta(days=9)).isoformat(),
                    "rate": "80.00",
                    "min_stay_arrival": 1,
                }
            ],
        )

    def test_seasons_change_rate_and_min_stay(self):
        SeasonRate.objects.create(
            name="Peak",
            start_date=self.today + timedelta(days=3),
            end_date=self.today + timedelta(days=4),
            percent=50,
            min_nights=2,
        )
        _a, restrictions = channex.build_ari(days=7)
        self.assertEqual(
            [(r["rate"], r["min_stay_arrival"]) for r in restrictions], [("80.00", 1), ("120.00", 2), ("80.00", 1)]
        )

    def test_out_of_order_and_unlinked_types(self):
        self.room2.out_of_order = True
        self.room2.save()
        availability, _r = channex.build_ari(days=3)
        self.assertEqual(availability[0]["availability"], 1)
        self.double.channex_room_type_id = ""
        self.double.save()
        self.assertEqual(channex.build_ari(days=3), ([], []))

    def test_push_only_when_something_changed(self):
        client = FakeClient()
        self.assertTrue(self.run_with(client, channex.push))
        self.assertFalse(self.run_with(client, channex.push))
        self.make_reservation(start=1)  # a booking marks it dirty
        self.assertTrue(ChannelSyncState.get().dirty)
        self.assertTrue(self.run_with(client, channex.push))
        self.assertTrue(client.sent_availability and client.sent_restrictions)

    def test_failed_push_stays_dirty(self):
        client = FakeClient()
        client.availability = mock.Mock(side_effect=channex.ChannexError("HTTP 500"))
        with self.assertRaises(channex.ChannexError):
            self.run_with(client, channex.push, force=True)
        state = ChannelSyncState.get()
        self.assertTrue(state.dirty)
        self.assertEqual(state.last_error, "HTTP 500")

    def test_nothing_happens_when_not_connected(self):
        HotelSettings.objects.filter(pk=1).update(channex_enabled=False)
        from apps.core.models import clear_settings_cache

        clear_settings_cache()
        self.assertFalse(channex.push(force=True))
        self.assertEqual(channex.pull(), [])

    # ----- Receiving -----

    def test_new_booking_becomes_a_reservation_and_is_acknowledged(self):
        client = FakeClient([revision("rev-1", arrival=self.a, departure=self.d)])
        (cb,) = self.run_with(client, channex.pull)
        self.assertEqual(client.acked, ["rev-1"])
        self.assertEqual(cb.problem, "")
        res = Reservation.objects.get(external_uid="cx:bk-1:0")
        self.assertEqual((res.source, res.external_ref, res.adults), ("booking_com", "998877", 2))
        self.assertEqual(res.nightly_rates, ["90.00", "100.00"])
        self.assertEqual(res.estimated_total, D("190.00"))
        self.assertEqual(
            (res.guest.first_name, res.guest.email, res.guest.nationality), ("Lena", "lena@example.com", "DE")
        )
        self.assertIn("998877", res.notes)

    def test_modified_dates_and_cancellation(self):
        client = FakeClient([revision("rev-1", arrival=self.a, departure=self.d)])
        self.run_with(client, channex.pull)
        later = self.d + timedelta(days=1)
        client.revisions = [revision("rev-2", status="modified", arrival=self.a, departure=later)]
        self.run_with(client, channex.pull)
        res = Reservation.objects.get(external_uid="cx:bk-1:0")
        self.assertEqual(res.departure, later)
        self.assertEqual(Reservation.objects.filter(external_uid__startswith="cx:").count(), 1)
        client.revisions = [revision("rev-3", status="cancelled", arrival=self.a, departure=later)]
        self.run_with(client, channex.pull)
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.CANCELLED)
        self.assertEqual(ChannelBooking.objects.get().status, "cancelled")

    def test_multi_room_booking_uses_two_rooms(self):
        rooms = revision("x", arrival=self.a, departure=self.d)["rooms"] * 2
        client = FakeClient([revision("rev-1", rooms=rooms, arrival=self.a, departure=self.d)])
        self.run_with(client, channex.pull)
        self.assertEqual(
            set(Reservation.objects.filter(external_uid__startswith="cx:").values_list("room_id", flat=True)),
            {self.room.pk, self.room2.pk},
        )

    def test_no_free_room_is_reported_not_overbooked(self):
        self.make_reservation(room=self.room, start=4, nights=2)
        self.make_reservation(room=self.room2, start=4, nights=2)
        client = FakeClient([revision("rev-1", arrival=self.a, departure=self.d)])
        (cb,) = self.run_with(client, channex.pull)
        self.assertTrue(cb.problem)
        self.assertEqual(client.acked, ["rev-1"])
        self.assertFalse(Reservation.objects.filter(external_uid__startswith="cx:").exists())
        self.client.login(username="boss", password=PASSWORD)
        self.assertContains(self.client.get("/"), reverse("frontdesk:channel_manager"))

    def test_unlinked_room_type_is_reported(self):
        rooms = revision("x", arrival=self.a, departure=self.d)["rooms"]
        rooms[0]["room_type_id"] = "cx-unknown"
        client = FakeClient([revision("rev-1", rooms=rooms, arrival=self.a, departure=self.d)])
        (cb,) = self.run_with(client, channex.pull)
        self.assertIn("cx-unknown", cb.problem)

    # ----- Pages -----

    def test_page_mapping_and_buttons(self):
        client = FakeClient()
        self.client.login(username="boss", password=PASSWORD)
        with mock.patch.object(channex.Client, "from_settings", return_value=client):
            page = self.client.get(reverse("frontdesk:channel_manager"))
            self.assertContains(page, "Best rate")
            self.client.post(
                reverse("frontdesk:channel_manager"),
                {"form": "mapping", f"rt{self.double.pk}": "cx-dbl", f"rp{self.double.pk}": "cx-dbl-bar"},
            )
            self.client.post(reverse("frontdesk:channel_manager_sync"), {"what": "push"})
        self.assertTrue(client.sent_availability)
        self.client.login(username="desk", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("frontdesk:channel_manager")).status_code, 403)

    def test_webhook_needs_the_secret(self):
        from apps.frontdesk.channel_manager import webhook_token

        self.assertEqual(self.client.post(reverse("channex_webhook", args=["wrong"])).status_code, 404)
        with mock.patch("apps.frontdesk.channel_manager.threading.Thread") as thread:
            r = self.client.post(reverse("channex_webhook", args=[webhook_token()]))
        self.assertEqual(r.content, b"OK")
        thread.assert_called_once()

    def test_secrets_are_not_in_the_settings_export(self):
        from apps.core import backup

        doc = backup.read_file(backup.export_settings())
        self.assertNotIn("channex_api_key", doc["data"]["hotel"])
        self.assertEqual(doc["data"]["hotel"]["channex_property_id"], "prop-1")
