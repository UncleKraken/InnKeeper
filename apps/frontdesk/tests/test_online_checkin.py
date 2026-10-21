from datetime import date, timedelta

from django.core import mail
from django.urls import reverse

from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import PASSWORD, HotelTestCase
from apps.frontdesk import checkin, guest_messages, register
from apps.frontdesk.models import Reservation, StayGuest


def person(prefix, **kw):
    data = {
        f"{prefix}-first_name": kw.get("first", "Lena"), f"{prefix}-last_name": kw.get("last", "Weber"),
        f"{prefix}-nationality": kw.get("nat", "Germany"), f"{prefix}-date_of_birth": kw.get("dob", "1990-05-01"),
        f"{prefix}-document_type": kw.get("doc_type", "passport"), f"{prefix}-document_number": kw.get("doc", "C01X00T47"),
    }
    return data


class OnlineCheckinTests(HotelTestCase):
    def setUp(self):
        hs = HotelSettings.load()
        hs.public_url = "https://book.example.al"
        hs.save()
        clear_settings_cache()
        self.res = self.make_reservation(start=3, nights=2)
        Reservation.objects.filter(pk=self.res.pk).update(adults=2, children=1)
        self.res.refresh_from_db()
        self.url = checkin.link(self.res)

    def test_link_is_private_and_stable(self):
        self.assertTrue(self.url.startswith("https://book.example.al/book/checkin/"))
        self.assertEqual(checkin.link(self.res), self.url)
        self.assertGreaterEqual(len(self.res.checkin_token), 16)
        self.assertEqual(self.client.get(reverse("booking:checkin", args=["x" * 20])).status_code, 404)

    def test_guest_checks_in_everyone(self):
        path = reverse("booking:checkin", args=[self.res.checkin_token])
        r = self.client.get(path)
        self.assertContains(r, "g0-document_number")
        self.assertContains(r, "a1-first_name")
        self.assertContains(r, "c1-first_name")
        # Required details are checked.
        r = self.client.post(path, {**person("g0", doc=""), **person("a1"), "c1-first_name": "Mia", "c1-last_name": "Weber"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(StayGuest.objects.exists())
        data = {**person("g0", first="Ana", last="Koci", nat="Albania", doc_type="id_card", doc="I12345678A"),
                **person("a1"), "c1-first_name": "Mia", "c1-last_name": "Weber", "c1-date_of_birth": "2018-03-02",
                "g0-arrival_time": "22:00"}
        r = self.client.post(path, data)
        self.assertRedirects(r, f"{path}?lang=sq&done=1", fetch_redirect_response=False)
        self.res.refresh_from_db()
        self.res.guest.refresh_from_db()
        self.assertIsNotNone(self.res.online_checkin_at)
        self.assertEqual(self.res.guest.document_number, "I12345678A")
        self.assertEqual(self.res.arrival_time, "22:00")
        self.assertEqual([(c.first_name, c.is_child) for c in self.res.companions.all()], [("Lena", False), ("Mia", True)])
        # Sending again replaces, never duplicates.
        self.client.post(path, data)
        self.assertEqual(self.res.companions.count(), 2)

    def test_future_dates_of_birth_are_refused(self):
        path = reverse("booking:checkin", args=[self.res.checkin_token])
        tomorrow = (date.today() + timedelta(days=2)).isoformat()
        r = self.client.post(path, {**person("g0", dob=tomorrow), **person("a1"), "c1-first_name": "M", "c1-last_name": "W", "c1-date_of_birth": "2018-01-01"})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(Reservation.objects.get(pk=self.res.pk).online_checkin_at)

    def test_stored_id_numbers_are_not_shown_to_a_link_alone(self):
        g = self.res.guest
        g.document_type, g.document_number = "passport", "SECRET99"
        g.save()
        self.assertNotContains(self.client.get(reverse("booking:checkin", args=[self.res.checkin_token])), "SECRET99")

    def test_closed_after_check_in_and_gone_after_departure(self):
        path = reverse("booking:checkin", args=[self.res.checkin_token])
        Reservation.objects.filter(pk=self.res.pk).update(status=Reservation.Status.CHECKED_IN)
        r = self.client.post(path, person("g0"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(StayGuest.objects.exists())
        Reservation.objects.filter(pk=self.res.pk).update(status=Reservation.Status.CANCELLED)
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_switched_off(self):
        hs = HotelSettings.load()
        hs.online_checkin = False
        hs.save()
        clear_settings_cache()
        self.assertEqual(self.client.get(reverse("booking:checkin", args=[self.res.checkin_token])).status_code, 404)
        self.assertFalse(checkin.offered(self.res))

    def test_arrival_email_carries_the_link(self):
        hs = HotelSettings.load()
        hs.smtp_host, hs.email_from = "smtp.example.com", "hotel@example.com"
        hs.save()
        clear_settings_cache()
        self.res.guest.email = "ana@example.com"
        self.res.guest.save()
        self.assertTrue(guest_messages.send(guest_messages.PRE_ARRIVAL, self.res, force=True))
        self.assertIn(self.res.checkin_token, mail.outbox[-1].body + "".join(a[0] for a in mail.outbox[-1].alternatives))

    def test_reception_fills_in_and_register_lists_everyone(self):
        self.client.login(username="desk", password=PASSWORD)
        url = reverse("frontdesk:stay_guests", args=[self.res.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        r = self.client.post(url, {"g0-first_name": "Ana", "g0-last_name": "Koci", **person("a1", doc=""), "c1-first_name": "", "c1-last_name": ""})
        self.assertRedirects(r, reverse("frontdesk:reservation_detail", args=[self.res.pk]), fetch_redirect_response=False)
        self.assertEqual(self.res.companions.count(), 1)  # the empty child row is skipped
        Reservation.objects.filter(pk=self.res.pk).update(status=Reservation.Status.CHECKED_IN, arrival=self.today, departure=self.today + timedelta(days=1))
        rows = register.people(register.stays(self.today, self.today))
        self.assertEqual([x["p"].first_name for x in rows], ["Ana", "Lena"])
        self.assertEqual(len(rows[1]["missing"]), 1)  # the document
        page = self.client.get(reverse("frontdesk:guest_register")).content.decode()
        self.assertIn("Weber", page)
        csv = self.client.get(reverse("frontdesk:guest_register"), {"format": "csv"}).content.decode("utf-8-sig")
        self.assertIn("Weber;Lena", csv)

    def test_reservation_page_offers_the_link(self):
        self.client.login(username="desk", password=PASSWORD)
        r = self.client.get(reverse("frontdesk:reservation_detail", args=[self.res.pk]))
        self.assertContains(r, self.res.checkin_token)
        self.assertContains(r, reverse("frontdesk:stay_guests", args=[self.res.pk]))


class CheckinLinkWithoutPublicAddressTests(HotelTestCase):
    def test_link_uses_the_wifi_address_not_this_computer_and_no_whatsapp(self):
        from unittest import mock

        self.guest.phone = "+355 69 1234567"
        self.guest.save()
        res = self.make_reservation(start=2, nights=2)
        self.client.login(username="desk", password=PASSWORD)
        with mock.patch("apps.core.remote.lan_address", return_value="192.168.1.20"):
            r = self.client.get(reverse("frontdesk:reservation_detail", args=[res.pk]), HTTP_HOST="127.0.0.1:8765")
        self.assertContains(r, "http://192.168.1.20:8765/book/checkin/")
        self.assertNotContains(r, "127.0.0.1:8765/book/checkin/")
        self.assertNotContains(r, "check%20in%20online")
