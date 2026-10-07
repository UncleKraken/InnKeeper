from datetime import date, timedelta

from django.urls import reverse

from apps.core.testing import PASSWORD, HotelTestCase
from apps.frontdesk import register, services
from apps.frontdesk.models import Guest, Reservation


class RegisterTests(HotelTestCase):
    def test_lists_checked_in_guests_and_flags_missing_data(self):
        res = self.make_reservation(status=Reservation.Status.CHECKED_IN)
        future = self.make_reservation(room=self.room2, start=5)
        rows = register.stays(self.today, self.today)
        self.assertEqual(rows, [res])
        self.assertNotIn(future, rows)
        self.assertIn("document", register.missing(self.guest))

    def test_foreign_filter(self):
        self.guest.nationality = "Shqipëri"
        self.guest.save()
        self.make_reservation(status=Reservation.Status.CHECKED_IN)
        lena = Guest.objects.create(first_name="Lena", last_name="Weber", nationality="Germany")
        other = self.make_reservation(room=self.room2, status=Reservation.Status.CHECKED_IN)
        Reservation.objects.filter(pk=other.pk).update(guest=lena)
        rows = register.stays(self.today, self.today, foreign_only=True)
        self.assertEqual([r.guest for r in rows], [lena])

    def test_page_and_csv(self):
        self.guest.document_type = "passport"
        self.guest.document_number = "AB123"
        self.guest.date_of_birth = date(1990, 5, 1)
        self.guest.save()
        self.make_reservation(status=Reservation.Status.CHECKED_IN)
        self.client.login(username="desk", password=PASSWORD)
        url = reverse("frontdesk:guest_register")
        self.assertContains(self.client.get(url), "AB123")
        resp = self.client.get(url, {"from": self.today.isoformat(), "format": "csv"})
        body = resp.content.decode("utf-8-sig")
        self.assertIn("Koci;Ana", body)
        self.assertIn("01.05.1990", body)
        self.client.login(username="cleaner", password=PASSWORD)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_check_in_reminds_about_missing_id(self):
        res = self.make_reservation()
        self.client.login(username="desk", password=PASSWORD)
        resp = self.client.post(reverse("frontdesk:check_in", args=[res.pk]), follow=True)
        self.assertTrue(any("ID" in str(m) or "pasaport" in str(m) for m in resp.context["messages"]))

    def test_old_stays_are_in_the_register_of_their_dates(self):
        res = self.make_reservation(status=Reservation.Status.CHECKED_IN)
        services.check_out(res, self.reception, allow_balance=True)
        self.assertEqual(len(register.stays(self.today - timedelta(days=1), self.today)), 1)
