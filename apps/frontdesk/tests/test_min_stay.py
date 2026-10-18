from datetime import timedelta
from decimal import Decimal as D

from django.urls import reverse

from apps.core.models import AuditLog
from apps.core.testing import PASSWORD, HotelTestCase
from apps.frontdesk.models import Reservation, SeasonRate


class ReceptionMinimumStayTests(HotelTestCase):
    def setUp(self):
        SeasonRate.objects.create(
            name="Summer", start_date=self.today, end_date=self.today + timedelta(days=30), percent=D("10"), min_nights=3
        )
        self.client.login(username="desk", password=PASSWORD)

    def _post(self, nights, **extra):
        return self.client.post(
            reverse("frontdesk:reservation_create"),
            {
                "new_first_name": "Ana", "new_last_name": "Leka", "room": self.room.pk,
                "arrival": self.today.isoformat(), "departure": (self.today + timedelta(days=nights)).isoformat(),
                "adults": 2, "children": 0, "source": "walk_in", **extra,
            },
        )

    def test_short_stay_needs_a_tick(self):
        r = self._post(1)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "3")
        self.assertContains(r, 'type="checkbox" name="allow_short_stay"')
        self.assertFalse(Reservation.objects.exists())
        r = self._post(1, allow_short_stay="on")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action="reservation.short_stay").exists())

    def test_long_enough_stay_has_no_question(self):
        page = self.client.get(reverse("frontdesk:reservation_create"))
        self.assertNotContains(page, 'type="checkbox" name="allow_short_stay"')
        self.assertEqual(self._post(3).status_code, 302)
