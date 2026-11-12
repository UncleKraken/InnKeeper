from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.core.exceptions import BusinessError
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Folio
from apps.frontdesk import services as fd
from apps.frontdesk.models import Reservation


class ForgottenCheckOutTests(HotelTestCase):
    """The guest left on the booked day, but nobody pressed check-out until weeks later."""

    def _overdue(self, nights=3, late=20):
        res = self.make_reservation(start=-(nights + late), nights=nights, status=Reservation.Status.CHECKED_IN)
        return res

    def test_page_asks_when_the_guest_left_and_does_not_add_nights_silently(self):
        res = self._overdue()
        self.client.login(username="desk", password=PASSWORD)
        r = self.client.get(reverse("frontdesk:reservation_detail", args=[res.pk]))
        self.assertContains(r, 'name="left" value="booked"')
        page = r.content.decode()
        self.assertIn("+", page)  # the extra nights are shown apart, as "only if"
        self.assertContains(r, f'action="{reverse("frontdesk:check_out", args=[res.pk])}" class="inline"', count=2)  # the two choices

    def test_left_as_booked_charges_only_the_booked_nights(self):
        res = self._overdue(nights=3, late=20)
        self.client.login(username="desk", password=PASSWORD)
        folio, _ = Folio.objects.get_or_create(reservation=res)
        due = res.amount_for_nights(0, 3)
        fd.add_payment(folio, amount=due, method="card", user=self.reception)
        self.client.post(reverse("frontdesk:check_out", args=[res.pk]), {"left": "booked"})
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.CHECKED_OUT)
        self.assertEqual(Folio.objects.get(reservation=res).accommodation_nights_posted(), 3)
        self.assertEqual(res.departure, timezone.localdate() - timedelta(days=20))

    def test_stayed_until_today_charges_the_extra_nights(self):
        res = self._overdue(nights=2, late=3)
        folio, _ = Folio.objects.get_or_create(reservation=res)
        fd.add_payment(folio, amount=res.amount_for_nights(0, 5), method="card", user=self.reception)
        fd.check_out(res, self.reception)
        res.refresh_from_db()
        self.assertEqual(Folio.objects.get(reservation=res).accommodation_nights_posted(), 5)

    def test_left_on_must_be_a_real_day_of_the_stay(self):
        res = self._overdue()
        for bad in (res.arrival, timezone.localdate() + timedelta(days=1)):
            with self.assertRaises(BusinessError):
                fd.check_out(res, self.reception, left_on=bad)

    def test_on_time_guests_keep_the_normal_button(self):
        res = self.make_reservation(start=-1, nights=2, status=Reservation.Status.CHECKED_IN)
        self.client.login(username="desk", password=PASSWORD)
        r = self.client.get(reverse("frontdesk:reservation_detail", args=[res.pk]))
        self.assertNotContains(r, 'name="left" value="booked"')
        self.assertContains(r, f'action="{reverse("frontdesk:check_out", args=[res.pk])}" class="inline"', count=1)


