import time

from django.core.cache import cache
from django.urls import reverse

from apps.accounts import twofactor
from apps.accounts.models import User
from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import PASSWORD, HotelTestCase


class TotpTests(HotelTestCase):
    def test_rfc6238_reference_values(self):
        # RFC 6238 test secret "12345678901234567890" (SHA1), 8 digits truncated to our 6.
        import base64

        secret = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(twofactor.code_at(secret, 59 // 30), "287082")
        self.assertEqual(twofactor.code_at(secret, 1111111109 // 30), "081804")

    def test_window_and_garbage(self):
        s = twofactor.new_secret()
        now = 1_800_000_000
        self.assertIsNotNone(twofactor.matching_step(s, twofactor.code_at(s, now // 30 - 1), at=now))
        self.assertIsNone(twofactor.matching_step(s, twofactor.code_at(s, now // 30 - 3), at=now))
        self.assertIsNone(twofactor.matching_step(s, "12ab", at=now))


class TwoStepFlowTests(HotelTestCase):
    def setUp(self):
        cache.clear()

    def switch_on(self, username="boss"):
        self.client.login(username=username, password=PASSWORD)
        self.client.get(reverse("accounts:two_step"))
        secret = self.client.session["innkeeper_new_totp"]
        code = twofactor.code_at(secret, twofactor.now_step())
        r = self.client.post(reverse("accounts:two_step"), {"code": code})
        self.assertRedirects(r, reverse("accounts:two_step"), fetch_redirect_response=False)
        page = self.client.get(reverse("accounts:two_step")).content.decode()
        self.client.logout()
        user = User.objects.get(username=username)
        self.assertTrue(user.has_two_step)
        self.assertEqual(len(user.recovery_codes), 8)
        return user, page

    def test_setup_shows_recovery_codes_once(self):
        user, page = self.switch_on()
        self.assertIn("recovery-codes", page)
        self.client.login(username="boss", password=PASSWORD)
        self.assertNotIn("recovery-codes", self.client.get(reverse("accounts:two_step")).content.decode())

    def test_wrong_setup_code_is_refused(self):
        self.client.login(username="boss", password=PASSWORD)
        self.client.get(reverse("accounts:two_step"))
        self.client.post(reverse("accounts:two_step"), {"code": "000000"})
        self.assertFalse(User.objects.get(username="boss").has_two_step)

    def test_password_alone_is_not_enough(self):
        user, _p = self.switch_on()
        r = self.client.post(reverse("accounts:login"), {"username": "boss", "password": PASSWORD, "next": "/finance/"})
        self.assertRedirects(r, reverse("accounts:two_step_verify"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get("/").status_code, 302)  # still signed out
        r = self.client.post(reverse("accounts:two_step_verify"), {"code": "123456"})
        self.assertNotIn("_auth_user_id", self.client.session)
        user.refresh_from_db()
        code = twofactor.code_at(user.totp_secret, twofactor.now_step() + 1)  # the next code is accepted too
        r = self.client.post(reverse("accounts:two_step_verify"), {"code": code})
        self.assertRedirects(r, "/finance/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        # The same code can't be used again.
        self.client.logout()
        self.client.post(reverse("accounts:login"), {"username": "boss", "password": PASSWORD})
        self.client.post(reverse("accounts:two_step_verify"), {"code": code})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_recovery_code_works_once(self):
        user, page = self.switch_on()
        import re

        codes = re.findall(r"<span>([a-z0-9]{4}-[a-z0-9]{4})</span>", page)
        self.assertEqual(len(codes), 8)
        self.client.post(reverse("accounts:login"), {"username": "boss", "password": PASSWORD})
        self.client.post(reverse("accounts:two_step_verify"), {"code": codes[0].upper().replace("-", "")})
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(len(User.objects.get(pk=user.pk).recovery_codes), 7)
        self.client.logout()
        self.client.post(reverse("accounts:login"), {"username": "boss", "password": PASSWORD})
        self.client.post(reverse("accounts:two_step_verify"), {"code": codes[0]})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_too_many_wrong_codes(self):
        self.switch_on()
        self.client.post(reverse("accounts:login"), {"username": "boss", "password": PASSWORD})
        for _i in range(6):
            r = self.client.post(reverse("accounts:two_step_verify"), {"code": "000000"})
        self.assertRedirects(r, reverse("accounts:login"), fetch_redirect_response=False)

    def test_pending_expires(self):
        self.switch_on()
        self.client.post(reverse("accounts:login"), {"username": "boss", "password": PASSWORD})
        s = self.client.session
        s[twofactor.PENDING]["at"] = time.time() - 600
        s.save()
        self.assertRedirects(self.client.get(reverse("accounts:two_step_verify")), reverse("accounts:login"), fetch_redirect_response=False)

    def test_switch_off_needs_the_password_and_manager_can_reset(self):
        self.switch_on("desk")
        self.client.post(reverse("accounts:login"), {"username": "desk", "password": PASSWORD})
        user = User.objects.get(username="desk")
        self.client.post(reverse("accounts:two_step_verify"), {"code": twofactor.code_at(user.totp_secret, twofactor.now_step())})
        self.client.post(reverse("accounts:two_step_off"), {"password": "wrong"})
        self.assertTrue(User.objects.get(pk=user.pk).has_two_step)
        self.client.logout()
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("accounts:staff_two_step_off", args=[user.pk]))
        self.assertFalse(User.objects.get(pk=user.pk).has_two_step)
        self.client.logout()
        self.client.login(username="desk", password=PASSWORD)
        self.assertEqual(self.client.post(reverse("accounts:staff_two_step_off", args=[self.manager.pk])).status_code, 403)

    def test_required_for_managers(self):
        hs = HotelSettings.load()
        hs.require_two_step = True
        hs.save()
        clear_settings_cache()
        self.client.login(username="boss", password=PASSWORD)
        self.assertRedirects(self.client.get("/"), reverse("accounts:two_step"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("accounts:two_step")).status_code, 200)
        self.client.logout()
        self.client.login(username="desk", password=PASSWORD)  # not a manager
        self.assertEqual(self.client.get("/").status_code, 200)
