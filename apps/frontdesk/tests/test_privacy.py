from decimal import Decimal

from django.urls import reverse

from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Folio
from apps.frontdesk import privacy
from apps.frontdesk.models import Guest, Reservation, StayGuest


class PrivacyNoticeTests(HotelTestCase):
    def test_public_notice_standard_and_own_text(self):
        r = self.client.get(reverse("booking:privacy") + "?lang=en")
        self.assertContains(r, "How we use your personal data")
        HotelSettings.objects.update(privacy_notice="Our own privacy text.")
        clear_settings_cache()
        r = self.client.get(reverse("booking:privacy"))
        self.assertContains(r, "Our own privacy text.")
        self.assertNotContains(r, "How we use your personal data")

    def test_linked_from_online_checkin(self):
        from apps.frontdesk import checkin

        res = self.make_reservation(start=2, nights=2)
        HotelSettings.objects.update(public_url="https://hotel.example.com")
        clear_settings_cache()
        r = self.client.get(reverse("booking:checkin", args=[checkin.ensure_token(res)]))
        self.assertContains(r, reverse("booking:privacy"))


class EraseGuestTests(HotelTestCase):
    def _guest_with_history(self):
        g = Guest.objects.create(
            first_name="Arta", last_name="Hoxha", email="arta@example.com", phone="+355691112233",
            nationality="Shqipëri", document_type="id_card", document_number="I1234567", address="Rr. 1", notes="likes quiet",
            date_of_birth="1990-01-01",
        )
        res = self.make_reservation(start=-5, nights=2)
        res.guest = g
        res.status = Reservation.Status.CHECKED_OUT
        res.notes = "late arrival"
        res.save()
        StayGuest.objects.create(reservation=res, first_name="Ilir", last_name="Hoxha", document_number="X9", date_of_birth="1988-02-02")
        folio, _ = Folio.objects.get_or_create(reservation=res)
        from apps.finance.models import Charge

        Charge.objects.create(folio=folio, kind="other", description="Room", quantity=1, unit_price=Decimal("50"))
        from apps.marketing.models import Contact

        Contact.objects.create(email="arta@example.com", name="Arta")
        return g, res

    def test_manager_erases_personal_details_bills_stay(self):
        g, res = self._guest_with_history()
        self.client.login(username="boss", password=PASSWORD)
        url = reverse("frontdesk:guest_erase", args=[g.pk])
        self.client.post(url, {"confirm": "no"})
        g.refresh_from_db()
        self.assertEqual(g.document_number, "I1234567")  # not confirmed
        self.client.post(url, {"confirm": "ERASE"})
        g.refresh_from_db()
        self.assertEqual((g.email, g.phone, g.document_number, g.address, g.notes, g.date_of_birth), ("", "", "", "", "", None))
        self.assertNotIn("Arta", g.full_name)
        comp = StayGuest.objects.get(reservation=res)
        self.assertEqual((comp.document_number, comp.date_of_birth), ("", None))
        res.refresh_from_db()
        self.assertEqual(res.notes, "")
        from apps.marketing.models import Contact

        self.assertFalse(Contact.objects.filter(email__iexact="arta@example.com").exists())
        self.assertEqual(Folio.objects.get(reservation=res).charges.count(), 1)  # bills stay

    def test_staff_cannot_and_current_guests_cannot_be_erased(self):
        g, _res = self._guest_with_history()
        self.client.login(username="desk", password=PASSWORD)
        self.client.post(reverse("frontdesk:guest_erase", args=[g.pk]), {"confirm": "ERASE"})
        g.refresh_from_db()
        self.assertEqual(g.document_number, "I1234567")
        future = self.make_reservation(room=self.room2, start=3, nights=1)
        from apps.core.exceptions import BusinessError

        with self.assertRaises(BusinessError):
            privacy.erase_guest(future.guest, self.manager)


class OldIdDetailsTests(HotelTestCase):
    def test_removed_after_the_chosen_years_only(self):
        old = self.make_reservation(start=-800, nights=2)
        old.status = Reservation.Status.CHECKED_OUT
        old.save()
        g = old.guest
        Guest.objects.filter(pk=g.pk).update(document_number="OLD1", date_of_birth="1980-05-05")
        StayGuest.objects.create(reservation=old, first_name="A", last_name="B", document_number="OLD2")
        recent_guest = Guest.objects.create(first_name="New", last_name="One", document_number="NEW1")
        recent = self.make_reservation(room=self.room2, start=-30, nights=2)
        recent.guest = recent_guest
        recent.status = Reservation.Status.CHECKED_OUT
        recent.save()
        self.assertEqual(privacy.remove_old_id_details(), 0)  # setting is 0: keep
        HotelSettings.objects.update(guest_id_keep_years=2)
        clear_settings_cache()
        self.assertEqual(privacy.remove_old_id_details(), 2)
        g.refresh_from_db()
        self.assertEqual((g.document_number, g.date_of_birth), ("", None))
        self.assertEqual(StayGuest.objects.get(reservation=old).document_number, "")
        recent_guest.refresh_from_db()
        self.assertEqual(recent_guest.document_number, "NEW1")
        self.assertEqual(privacy.remove_old_id_details(), 0)  # nothing left to do


class SupportContactTests(HotelTestCase):
    def test_shown_under_help_and_about(self):
        self.client.login(username="desk", password=PASSWORD)
        self.assertNotContains(self.client.get(reverse("core:help")), "Ardit Support")
        HotelSettings.objects.update(support_contact="Ardit Support\n+355 69 000 0000\nhelp@example.com")
        clear_settings_cache()
        self.assertContains(self.client.get(reverse("core:help")), "Ardit Support")
        r = self.client.get(reverse("core:about"))
        self.assertContains(r, "Ardit Support")
        self.assertContains(r, 'href="mailto:help@example.com"')
