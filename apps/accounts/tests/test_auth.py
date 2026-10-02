from datetime import timedelta

from django.core.cache import cache
from django.urls import reverse

from apps.accounts.models import User
from apps.core.testing import PASSWORD, HotelTestCase
from apps.frontdesk.models import Reservation


class LoginTests(HotelTestCase):
    def setUp(self):
        cache.clear()

    def test_unknown_username_cannot_sign_in(self):
        """Regression: the old app created an account for any unknown username."""
        resp = self.client.post(reverse("accounts:login"), {"username": "stranger", "password": "whatever123"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="stranger").exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_passwords_are_hashed(self):
        self.assertNotEqual(self.reception.password, PASSWORD)
        self.assertTrue(self.reception.password.startswith(("pbkdf2_", "argon2", "bcrypt", "scrypt")))

    def test_lockout_after_repeated_failures(self):
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": "desk", "password": "wrong-password"})
        resp = self.client.post(reverse("accounts:login"), {"username": "desk", "password": PASSWORD})
        self.assertContains(resp, "15")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_successful_login(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "desk", "password": PASSWORD})
        self.assertRedirects(resp, reverse("core:dashboard"))


class PermissionTests(HotelTestCase):
    def assertStatus(self, user, url_name, expected, *args):
        self.client.force_login(user)
        resp = self.client.get(reverse(url_name, args=args))
        self.assertEqual(resp.status_code, expected, f"{user.username} → {url_name}")

    def test_role_access(self):
        self.assertStatus(self.reception, "frontdesk:rack", 200)
        self.assertStatus(self.reception, "finance:dashboard", 403)
        self.assertStatus(self.reception, "accounts:staff_list", 403)
        self.assertStatus(self.waiter, "frontdesk:rack", 403)
        self.assertStatus(self.waiter, "outlets:floor", 200, self.restaurant.pk)
        self.assertStatus(self.cleaner, "housekeeping:board", 200)
        self.assertStatus(self.cleaner, "frontdesk:reservation_list", 403)
        self.assertStatus(self.accountant, "finance:dashboard", 200)
        self.assertStatus(self.accountant, "core:settings", 403)
        self.assertStatus(self.manager, "accounts:staff_list", 200)
        self.assertStatus(self.manager, "core:audit_log", 200)

    def test_anonymous_users_are_sent_to_login(self):
        resp = self.client.get(reverse("frontdesk:rack"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp["Location"])

    def test_staff_list_never_shows_passwords(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("accounts:staff_list"))
        self.assertNotContains(resp, self.reception.password)


class PageTests(HotelTestCase):
    """Every main page renders in both languages."""

    def test_pages_render(self):
        res = self.make_reservation()
        self.client.force_login(self.manager)
        urls = [
            reverse("core:dashboard"),
            reverse("frontdesk:rack"),
            reverse("frontdesk:reservation_list") + "?view=all",
            reverse("frontdesk:reservation_create"),
            reverse("frontdesk:reservation_detail", args=[res.pk]),
            reverse("frontdesk:invoice", args=[res.pk]),
            reverse("frontdesk:guest_list"),
            reverse("housekeeping:board"),
            reverse("housekeeping:ticket_list"),
            reverse("outlets:floor", args=[self.restaurant.pk]),
            reverse("outlets:setup"),
            reverse("finance:dashboard"),
            reverse("finance:ledger") + "?format=csv",
            reverse("core:settings"),
        ]
        for lang in ("sq", "en"):
            self.client.cookies["django_language"] = lang
            for url in urls:
                with self.subTest(url=url, lang=lang):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_booking_through_the_form(self):
        self.client.force_login(self.reception)
        resp = self.client.post(
            reverse("frontdesk:reservation_create"),
            {
                "new_first_name": "Erion",
                "new_last_name": "Hoxha",
                "room": self.room2.pk,
                "arrival": self.today.isoformat(),
                "departure": (self.today + timedelta(days=2)).isoformat(),
                "adults": 2,
                "children": 0,
                "source": "phone",
            },
        )
        self.assertEqual(resp.status_code, 302)
        res = Reservation.objects.get(guest__last_name="Hoxha")
        self.assertEqual(res.rate, self.double.base_rate)
