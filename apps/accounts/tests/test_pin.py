from django.urls import reverse

from apps.accounts.pin import COOKIE, check_pin_strength
from apps.core.models import AuditLog
from apps.core.testing import PASSWORD, HotelTestCase


class PinTests(HotelTestCase):
    def _make_shared(self):
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("accounts:shared_till"), {"on": "1"})
        self.client.post(reverse("accounts:lock"))

    def setUp(self):
        self.waiter.set_pin("4826")
        self.waiter.save()

    def test_strength(self):
        self.assertIsNotNone(check_pin_strength("1234"))
        self.assertIsNotNone(check_pin_strength("7777"))
        self.assertIsNotNone(check_pin_strength("12a4"))
        self.assertIsNotNone(check_pin_strength("123"))
        self.assertIsNone(check_pin_strength("4826"))
        self.assertTrue(self.waiter.check_pin("4826"))
        self.assertNotIn("4826", self.waiter.pin)  # hashed

    def test_pin_pad_only_on_a_shared_till(self):
        r = self.client.get(reverse("accounts:pin_pad"))
        self.assertRedirects(r, reverse("accounts:login"), fetch_redirect_response=False)
        # a forged cookie is ignored
        self.client.cookies[COOKIE] = "1"
        r = self.client.post(reverse("accounts:pin_pad"), {"user": self.waiter.pk, "pin": "4826"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_shared_till_switch_and_lock(self):
        self._make_shared()
        r = self.client.get(reverse("accounts:login"))
        self.assertRedirects(r, "/accounts/pin/?next=/", fetch_redirect_response=False)
        page = self.client.get(reverse("accounts:pin_pad"))
        self.assertContains(page, self.waiter.first_name or self.waiter.username)
        r = self.client.post(reverse("accounts:pin_pad"), {"user": self.waiter.pk, "pin": "4826", "next": "/outlets/"})
        self.assertRedirects(r, "/outlets/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.waiter.pk)
        self.assertTrue(AuditLog.objects.filter(action="auth.pin_login", user=self.waiter).exists())
        home = self.client.get("/outlets/", follow=True)
        self.assertContains(home, reverse("accounts:lock"))
        r = self.client.post(reverse("accounts:lock"), {"next": "/outlets/"})
        self.assertRedirects(r, f"/accounts/pin/?next=/outlets/&by={self.waiter.pk}", fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        # someone else unlocking starts at their own home, not on the last person's page
        self.reception.set_pin("5931")
        self.reception.save()
        r = self.client.post(reverse("accounts:pin_pad"), {"user": self.reception.pk, "pin": "5931", "next": "/outlets/", "by": self.waiter.pk})
        self.assertRedirects(r, "/", fetch_redirect_response=False)
        self.client.post(reverse("accounts:lock"))
        # password sign-in is still possible
        self.assertEqual(self.client.get(reverse("accounts:login") + "?password=1").status_code, 200)

    def test_wrong_pins_lock_that_person(self):
        self._make_shared()
        for _i in range(5):
            r = self.client.post(reverse("accounts:pin_pad"), {"user": self.waiter.pk, "pin": "0000"})
            self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("accounts:pin_pad"), {"user": self.waiter.pk, "pin": "4826"})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(r.status_code, 200)

    def test_set_own_pin_needs_password_and_manager_sets_others(self):
        self.client.login(username="desk", password=PASSWORD)
        self.client.post(reverse("accounts:my_pin"), {"password": "wrong", "pin1": "5931", "pin2": "5931"})
        self.reception.refresh_from_db()
        self.assertFalse(self.reception.has_pin)
        self.client.post(reverse("accounts:my_pin"), {"password": PASSWORD, "pin1": "5931", "pin2": "5931"})
        self.reception.refresh_from_db()
        self.assertTrue(self.reception.check_pin("5931"))
        # staff can't set someone else's
        self.assertNotEqual(self.client.get(reverse("accounts:staff_set_pin", args=[self.waiter.pk])).status_code, 200)
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("accounts:staff_set_pin", args=[self.reception.pk]), {"remove": "1"})
        self.reception.refresh_from_db()
        self.assertFalse(self.reception.has_pin)
        self.assertEqual(self.client.get(reverse("core:settings") + "?tab=tills").status_code, 200)
        self.client.post(reverse("core:settings") + "?tab=tills", {"pin_lock_minutes": "5"})
        from apps.core.models import HotelSettings

        self.assertEqual(HotelSettings.objects.get().pin_lock_minutes, 5)
