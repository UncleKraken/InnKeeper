from datetime import timedelta
from unittest import mock

from django.urls import reverse

from apps.core.testing import PASSWORD, HotelTestCase
from apps.frontdesk import ical
from apps.frontdesk.models import CalendarFeed, Reservation


def calendar(*events):
    body = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Booking.com//EN"]
    for uid, start, end, *rest in events:
        body += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{end:%Y%m%d}",
            "SUMMARY:CLOSED - Not available",
        ]
        if rest:
            body.append(f"STATUS:{rest[0]}")
        body.append("END:VEVENT")
    body.append("END:VCALENDAR")
    return "\r\n".join(body)


class CalendarSyncTests(HotelTestCase):
    def setUp(self):
        self.feed = CalendarFeed.objects.create(room=self.room, source="booking_com", url="https://example.com/a.ics")
        self.d = self.today + timedelta(days=3)

    def sync(self, text):
        with mock.patch.object(ical, "fetch", return_value=text):
            return ical.sync_feed(self.feed)

    def test_parse_handles_folding_datetimes_and_missing_end(self):
        text = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:abc\r\n def@x\r\nDTSTART:20261010T140000\r\n"
            "SUMMARY:Hello\\, world\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        (ev,) = ical.parse(text)
        self.assertEqual(ev.uid, "abcdef@x")
        self.assertEqual((ev.start.isoformat(), ev.end.isoformat()), ("2026-10-10", "2026-10-11"))
        self.assertEqual(ev.summary, "Hello, world")
        with self.assertRaises(ValueError):
            ical.parse("<html>not a calendar</html>")

    def test_new_bookings_are_imported(self):
        r = self.sync(calendar(("b1", self.d, self.d + timedelta(days=2))))
        self.assertEqual((r.created, r.conflicts), (1, []))
        res = Reservation.objects.get(external_uid="b1")
        self.assertEqual((res.room, res.source, res.nights), (self.room, "booking_com", 2))
        self.assertEqual(res.rate, self.double.base_rate)
        self.assertEqual(res.guest.first_name, "Booking.com")
        # Same calendar again: nothing new.
        r = self.sync(calendar(("b1", self.d, self.d + timedelta(days=2))))
        self.assertEqual((r.created, r.updated), (0, 0))

    def test_changed_dates_are_updated_and_removed_bookings_cancelled(self):
        self.sync(
            calendar(
                ("b1", self.d, self.d + timedelta(days=2)),
                ("b2", self.d + timedelta(days=5), self.d + timedelta(days=6)),
            )
        )
        r = self.sync(calendar(("b1", self.d, self.d + timedelta(days=3))))
        self.assertEqual((r.updated, r.cancelled), (1, 1))
        self.assertEqual(Reservation.objects.get(external_uid="b1").nights, 3)
        self.assertEqual(Reservation.objects.get(external_uid="b2").status, Reservation.Status.CANCELLED)

    def test_cancelled_status_and_past_events_are_ignored(self):
        r = self.sync(
            calendar(
                ("c1", self.d, self.d + timedelta(days=1), "CANCELLED"),
                ("old", self.today - timedelta(days=5), self.today - timedelta(days=2)),
            )
        )
        self.assertEqual(r.created, 0)

    def test_overlap_with_an_existing_booking_is_reported_not_overbooked(self):
        self.make_reservation(start=3, nights=2)
        r = self.sync(calendar(("b1", self.d + timedelta(days=1), self.d + timedelta(days=3))))
        self.assertEqual(r.created, 0)
        self.assertEqual(len(r.conflicts), 1)
        self.feed.refresh_from_db()
        self.assertEqual(len(self.feed.conflicts), 1)
        self.assertEqual(Reservation.objects.filter(room=self.room).count(), 1)

    def test_network_errors_are_recorded(self):
        with mock.patch.object(ical, "fetch", side_effect=OSError("timed out")):
            r = ical.sync_feed(self.feed)
        self.assertEqual(r.error, "timed out")
        self.feed.refresh_from_db()
        self.assertEqual(self.feed.last_error, "timed out")

    def test_checked_in_guests_are_never_cancelled_by_a_channel(self):
        self.d = self.today
        self.sync(calendar(("b1", self.today, self.today + timedelta(days=2))))
        Reservation.objects.filter(external_uid="b1").update(status=Reservation.Status.CHECKED_IN)
        r = self.sync(calendar())
        self.assertEqual(r.cancelled, 0)

    def test_room_export_lists_bookings_without_names(self):
        self.make_reservation(start=2, nights=3)
        url = reverse("ical_room", args=[ical.room_token(self.room)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(f"DTSTART;VALUE=DATE:{self.today + timedelta(days=2):%Y%m%d}", body)
        self.assertNotIn("Koci", body)
        self.assertEqual(len(ical.parse(body)), 1)
        self.assertEqual(self.client.get(reverse("ical_room", args=["1-forged"])).status_code, 404)
        # Another room's token can't be guessed from this one.
        self.assertNotEqual(ical.room_token(self.room), ical.room_token(self.room2))

    def test_channels_page_add_and_sync(self):
        self.client.login(username="boss", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("frontdesk:channels")).status_code, 200)
        with mock.patch.object(ical, "fetch", return_value=calendar(("x", self.d, self.d + timedelta(days=1)))):
            self.client.post(
                reverse("frontdesk:channels"),
                {"room": self.room2.pk, "source": "airbnb", "url": "webcal://airbnb.example/cal.ics"},
            )
        feed = CalendarFeed.objects.get(room=self.room2)
        self.assertTrue(feed.url.startswith("https://"))
        self.assertTrue(Reservation.objects.filter(feed=feed, source="airbnb").exists())
        self.client.login(username="desk", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("frontdesk:channels")).status_code, 403)
