from datetime import datetime, time, timedelta
from unittest import mock

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase
from apps.frontdesk import guest_messages as gm
from apps.frontdesk.models import Reservation


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class GuestMessageTests(HotelTestCase):
    def setUp(self):
        hs = HotelSettings.load()
        hs.smtp_host, hs.smtp_username, hs.email_from = "smtp.example.com", "hotel@example.com", "hotel@example.com"
        hs.address, hs.phone = "Rruga e Durrësit 1, Tiranë", "+355 69 000 0000"
        hs.message_pre_arrival = True
        hs.message_pre_arrival_text = "Parking behind the hotel. Wi-Fi: hotel123"
        hs.message_review = True
        hs.message_review_url = "https://g.page/r/example/review"
        hs.message_hour = 9
        hs.save()
        self.guest.email = "ana@example.com"
        self.guest.phone = "069 123 4567"
        self.guest.nationality = "Germany"
        self.guest.save()
        self.patcher = mock.patch("apps.core.email.connection", return_value=None)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def at(self, hour, days=0):
        return timezone.make_aware(datetime.combine(self.today + timedelta(days=days), time(hour)))

    def booking(self, start=2, room=None):
        res = self.make_reservation(start=start, nights=2, room=room)
        Reservation.objects.filter(pk=res.pk).update(created_at=timezone.now() - timedelta(days=5))
        return res

    def test_arrival_info_once_at_the_hour(self):
        res = self.booking(start=2)
        self.assertEqual(gm.run(self.at(8)), 0)  # before the chosen hour
        self.assertEqual(gm.run(self.at(10)), 1)
        self.assertEqual(gm.run(self.at(11)), 0)  # only once
        msg = mail.outbox[-1]
        self.assertEqual(msg.to, ["ana@example.com"])
        self.assertIn("Parking behind the hotel", msg.body)
        self.assertIn("google.com/maps", msg.alternatives[0][0])
        res.refresh_from_db()
        self.assertIsNotNone(res.pre_arrival_sent_at)

    def test_not_too_early_unconfirmed_or_cancelled(self):
        self.booking(start=6)  # more than 2 days ahead
        unconfirmed = self.booking(start=1, room=self.room2)
        Reservation.objects.filter(pk=unconfirmed.pk).update(confirmed=False)
        cancelled = self.booking(start=1)
        Reservation.objects.filter(pk=cancelled.pk).update(status=Reservation.Status.CANCELLED)
        self.assertEqual(gm.run(self.at(10)), 0)

    def test_review_the_day_after_check_out(self):
        res = self.make_reservation(start=-2, nights=2, status=Reservation.Status.CHECKED_OUT)
        Reservation.objects.filter(pk=res.pk).update(checked_out_at=self.at(11))
        self.assertEqual(gm.run(self.at(15)), 0)  # same day: not yet
        self.assertEqual(gm.run(self.at(10, days=1)), 1)
        self.assertIn("g.page/r/example/review", mail.outbox[-1].body)
        self.assertEqual(gm.run(self.at(10, days=2)), 0)

    def test_failed_email_is_retried(self):
        self.booking(start=1)
        with mock.patch("apps.core.email.send", return_value=False):
            self.assertEqual(gm.run(self.at(10)), 0)
        self.assertEqual(gm.run(self.at(10)), 1)

    def test_language_follows_the_guest(self):
        res = self.booking(start=1)
        gm.run(self.at(10))
        self.assertIn("Check-in is from", mail.outbox[-1].body)
        self.guest.nationality = "Albania"
        self.guest.save()
        res.refresh_from_db()
        self.assertEqual(gm.language(res), "sq")

    def test_whatsapp_numbers(self):
        self.assertEqual(gm.whatsapp_number("069 123 4567"), "355691234567")
        self.assertEqual(gm.whatsapp_number("+49 151 2345678"), "491512345678")
        self.assertEqual(gm.whatsapp_number("0049 151 2345678"), "491512345678")
        self.assertEqual(gm.whatsapp_number("12"), "")
        res = self.booking(start=1)
        link = gm.whatsapp_link(gm.PRE_ARRIVAL, res)
        self.assertTrue(link.startswith("https://wa.me/355691234567?text="))

    def test_reservation_page_and_send_by_hand(self):
        res = self.booking(start=5)
        self.client.login(username="desk", password=PASSWORD)
        r = self.client.get(reverse("frontdesk:reservation_detail", args=[res.pk]))
        self.assertContains(r, "wa.me/355691234567")
        self.client.post(reverse("frontdesk:send_guest_message", args=[res.pk]), {"kind": "pre_arrival"})
        self.assertEqual(len(mail.outbox), 1)
        self.client.post(reverse("frontdesk:send_guest_message", args=[res.pk]), {"kind": "pre_arrival"})
        self.assertEqual(len(mail.outbox), 2)  # by hand it can be sent again

    def test_settings_tab(self):
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.get(reverse("core:settings") + "?tab=messages")
        self.assertContains(r, "Parking behind the hotel")
        r = self.client.post(
            reverse("core:settings") + "?tab=messages",
            {"message_review": "on", "message_review_url": "", "message_pre_arrival_days": "2", "message_hour": "10"},
        )
        self.assertEqual(r.status_code, 200)  # the review link is needed
