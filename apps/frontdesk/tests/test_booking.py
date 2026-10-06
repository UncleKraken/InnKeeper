from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.core.cache import cache
from django.urls import reverse

from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Charge
from apps.frontdesk import booking, services
from apps.frontdesk.models import Reservation, SeasonRate
from apps.frontdesk.pricing import apply_quote, quote


class SeasonPricingTests(HotelTestCase):
    def test_base_rate_without_seasons(self):
        q = quote(self.double, self.today, self.today + timedelta(days=3))
        self.assertEqual(q.nightly, [Decimal("80.00")] * 3)
        self.assertFalse(q.varies)

    def test_percentage_and_fixed_seasons(self):
        d = self.today
        SeasonRate.objects.create(
            name="Summer", start_date=d + timedelta(days=1), end_date=d + timedelta(days=5), percent=25
        )
        SeasonRate.objects.create(
            name="Event",
            room_type=self.double,
            start_date=d + timedelta(days=3),
            end_date=d + timedelta(days=3),
            rate=Decimal("150"),
            min_nights=2,
        )
        q = quote(self.double, d, d + timedelta(days=5))
        self.assertEqual([str(x) for x in q.nightly], ["80.00", "100.00", "100.00", "150.00", "100.00"])
        self.assertEqual(q.total, Decimal("530.00"))
        self.assertEqual(q.min_nights, 2)
        self.assertTrue(q.varies)
        self.assertFalse(quote(self.double, d + timedelta(days=3), d + timedelta(days=4)).meets_min_nights)

    def test_inactive_seasons_are_ignored(self):
        SeasonRate.objects.create(
            name="Off", start_date=self.today, end_date=self.today + timedelta(days=9), percent=50, is_active=False
        )
        self.assertEqual(quote(self.double, self.today, self.today + timedelta(days=1)).nightly, [Decimal("80.00")])

    def test_accommodation_is_posted_per_price_run(self):
        d = self.today
        SeasonRate.objects.create(
            name="Peak", start_date=d + timedelta(days=2), end_date=d + timedelta(days=9), percent=50
        )
        res = self.make_reservation(nights=4, status=Reservation.Status.CHECKED_IN)
        apply_quote(res, quote(self.double, res.arrival, res.departure))
        res.save()
        self.assertEqual(res.estimated_total, Decimal("400.00"))  # 80 + 80 + 120 + 120
        services.post_accommodation(res, self.reception, on_date=res.departure)
        charges = Charge.objects.filter(folio=res.folio, kind=Charge.Kind.ACCOMMODATION).order_by("pk")
        self.assertEqual([(c.quantity, c.unit_price) for c in charges], [(2, Decimal("80.00")), (2, Decimal("120.00"))])
        self.assertEqual(res.folio.balance, Decimal("400.00"))
        # Running it again posts nothing more.
        self.assertIsNone(services.post_accommodation(res, self.reception, on_date=res.departure))

    def test_reservation_form_uses_the_price_list_when_rate_is_blank(self):
        d = self.today + timedelta(days=1)
        SeasonRate.objects.create(name="Peak", start_date=d, end_date=d, percent=50)
        self.client.login(username="desk", password=PASSWORD)
        r = self.client.post(
            reverse("frontdesk:reservation_create"),
            {
                "guest": self.guest.pk,
                "room": self.room.pk,
                "arrival": d.isoformat(),
                "departure": (d + timedelta(days=2)).isoformat(),
                "adults": 2,
                "children": 0,
                "rate": "",
                "source": "phone",
            },
        )
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        res = Reservation.objects.latest("pk")
        self.assertEqual(res.nightly_rates, ["120.00", "80.00"])
        self.assertEqual(res.estimated_total, Decimal("200.00"))


class OnlineBookingTests(HotelTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        hs = HotelSettings.load()
        hs.booking_enabled = True
        hs.booking_deposit_percent = 30
        hs.notify_email = "desk@hotel.test"
        hs.smtp_host = "smtp.hotel.test"
        hs.email_from = "hotel@hotel.test"
        hs.bank_details = "IBAN AL00 TEST"
        hs.save()
        cls.double.bookable_online = True
        cls.double.save()

    def setUp(self):
        cache.clear()
        self.arrival = self.today + timedelta(days=5)
        self.departure = self.arrival + timedelta(days=2)

    def guest_data(self, **kw):
        return {
            "first_name": "Lena",
            "last_name": "Weber",
            "email": "lena@example.com",
            "phone": "+49 1",
            "notes": "",
            **kw,
        }

    def book(self, **kw):
        return booking.create_online_booking(
            self.double, self.arrival, self.departure, 2, 0, self.guest_data(**kw), language="en"
        )

    def test_search_counts_free_rooms(self):
        (offer,) = booking.search(self.arrival, self.departure, 2, 0)
        self.assertEqual(offer.available, 2)
        self.assertEqual(booking.search(self.arrival, self.departure, 3, 0), [])  # too many adults
        self.make_reservation(start=5, nights=1)
        self.assertEqual(booking.search(self.arrival, self.departure, 2, 0)[0].available, 1)

    def test_booking_is_a_request_with_deposit_and_emails(self):
        res = self.book()
        self.assertFalse(res.confirmed)
        self.assertEqual(res.source, Reservation.Source.WEBSITE)
        self.assertEqual(res.deposit_due, Decimal("48.00"))
        self.assertGreaterEqual(len(res.booking_token), 16)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["desk@hotel.test", "lena@example.com"])
        guest_mail = next(m for m in mail.outbox if m.to == ["lena@example.com"])
        self.assertIn(res.code, guest_mail.subject)
        self.assertIn("IBAN AL00 TEST", guest_mail.alternatives[0][0])

    def test_returning_guest_is_reused(self):
        first = self.book()
        second = booking.create_online_booking(
            self.double,
            self.today + timedelta(days=20),
            self.today + timedelta(days=21),
            1,
            0,
            self.guest_data(email="LENA@example.com"),
            language="en",
        )
        self.assertEqual(first.guest_id, second.guest_id)

    def test_fills_every_free_room_then_refuses(self):
        self.book()
        self.book()
        with self.assertRaises(BusinessError):
            self.book()

    def test_dates_are_checked(self):
        with self.assertRaises(BusinessError):
            booking.create_online_booking(
                self.double,
                self.today - timedelta(days=1),
                self.today + timedelta(days=1),
                2,
                0,
                self.guest_data(),
                language="en",
            )
        hs = HotelSettings.load()
        hs.booking_max_days_ahead = 3
        hs.save()
        self.assertIsNotNone(booking.check_dates(self.arrival, self.departure))

    def test_confirm_and_decline(self):
        res = self.book()
        mail.outbox.clear()
        booking.confirm(res, self.reception)
        res.refresh_from_db()
        self.assertTrue(res.confirmed)
        self.assertIn("confirmed", mail.outbox[0].subject)
        other = self.book()
        booking.decline(other, self.reception, reason="Fully booked")
        other.refresh_from_db()
        self.assertEqual(other.status, Reservation.Status.CANCELLED)
        self.assertIn("Fully booked", mail.outbox[-1].alternatives[0][0])

    def test_instant_confirmation_when_turned_on(self):
        hs = HotelSettings.load()
        hs.booking_requires_confirmation = False
        hs.save()
        self.assertTrue(self.book().confirmed)

    def test_no_email_without_smtp(self):
        hs = HotelSettings.load()
        hs.smtp_host = ""
        hs.save()
        self.book()
        self.assertEqual(mail.outbox, [])

    # ----- Public pages -----

    def details_url(self):
        return (
            reverse("booking:details", args=[self.double.pk])
            + f"?arrival={self.arrival}&departure={self.departure}&adults=2&children=0&lang=en"
        )

    def post_details(self, **extra):
        data = {**self.guest_data(), "accept": "on", "website": "", **extra}
        return self.client.post(self.details_url(), data)

    def test_public_pages_are_404_when_booking_is_off(self):
        hs = HotelSettings.load()
        hs.booking_enabled = False
        hs.save()
        self.assertEqual(self.client.get(reverse("booking:search")).status_code, 404)
        self.assertEqual(self.client.get(self.details_url()).status_code, 404)

    def test_public_search_and_booking(self):
        r = self.client.get(
            reverse("booking:search"),
            {"arrival": self.arrival, "departure": self.departure, "adults": 2, "children": 0},
        )
        self.assertContains(r, "Double")
        r = self.post_details()
        res = Reservation.objects.get(source=Reservation.Source.WEBSITE)
        self.assertRedirects(r, reverse("booking:status", args=[res.booking_token]) + "?lang=en")
        page = self.client.get(reverse("booking:status", args=[res.booking_token]))
        self.assertContains(page, res.code)
        self.assertContains(page, "IBAN AL00 TEST")

    def test_honeypot_blocks_bots(self):
        r = self.post_details(website="http://spam.example")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Reservation.objects.filter(source=Reservation.Source.WEBSITE).exists())

    def test_rate_limit_per_connection(self):
        cache.set("innkeeper:booking-ip:127.0.0.1", 5, 3600)
        r = self.post_details()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Reservation.objects.filter(source=Reservation.Source.WEBSITE).exists())

    def test_unknown_token_is_404(self):
        self.assertEqual(self.client.get(reverse("booking:status", args=["x" * 22])).status_code, 404)

    def test_reception_confirms_from_the_app(self):
        res = self.book()
        self.client.login(username="desk", password=PASSWORD)
        self.assertContains(self.client.get(reverse("frontdesk:reservation_list") + "?view=online"), res.code)
        self.client.post(reverse("frontdesk:confirm_booking", args=[res.pk]))
        res.refresh_from_db()
        self.assertTrue(res.confirmed)

    def test_email_test_button(self):
        self.client.login(username="boss", password=PASSWORD)
        self.manager.email = "boss@hotel.test"
        self.manager.save()
        self.client.post(reverse("core:email_test"))
        self.assertEqual(mail.outbox[-1].to, ["boss@hotel.test"])
