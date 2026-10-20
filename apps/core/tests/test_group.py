import io
import json
import urllib.error
from decimal import Decimal as D
from unittest import mock

from django.core.cache import cache
from django.urls import reverse

from apps.core import group
from apps.core.models import GroupMember, HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class GroupOverviewTests(HotelTestCase):
    def setUp(self):
        cache.clear()

    def share(self):
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("core:group_sharing"), {"on": "1"})
        self.client.logout()
        return HotelSettings.load().group_token

    def test_summary_needs_the_key_and_has_no_names(self):
        self.assertEqual(self.client.get(reverse("core:group_summary")).status_code, 404)  # not shared
        key = self.share()
        self.assertEqual(len(key), 43)
        self.assertEqual(self.client.get(reverse("core:group_summary")).status_code, 403)
        r = self.client.get(reverse("core:group_summary"), HTTP_AUTHORIZATION="Bearer wrong")
        self.assertEqual(r.status_code, 403)
        self.make_reservation(start=0, nights=1)
        r = self.client.get(reverse("core:group_summary"), HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("sales_today", data)
        self.assertEqual(data["rooms"]["arrivals"], 1)
        self.assertNotIn("Koci", json.dumps(data))  # no guest names

    def test_too_many_wrong_keys(self):
        self.share()
        for _i in range(20):
            self.client.get(reverse("core:group_summary"), HTTP_AUTHORIZATION="Bearer wrong")
        self.assertEqual(self.client.get(reverse("core:group_summary"), HTTP_AUTHORIZATION="Bearer wrong").status_code, 429)

    def test_stop_sharing(self):
        key = self.share()
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("core:group_sharing"), {"on": "0"})
        self.assertEqual(self.client.get(reverse("core:group_summary"), HTTP_AUTHORIZATION=f"Bearer {key}").status_code, 404)

    def test_overview_combines_businesses(self):
        GroupMember.objects.create(name="Bar Blloku", url="http://100.64.0.9:8765", token="k1")
        GroupMember.objects.create(name="Villa Sarandë", url="http://100.64.0.10:8765", token="k2")
        remote = {
            "name": "Bar Blloku", "currency": "EUR", "symbol": "€", "sales_today": "250.00", "sales_yesterday": "200.00",
            "sales_month": "4000.00", "received_today": "240.00", "open_bills": 3, "open_bills_total": "45.00",
            "at_work": 4, "warnings": ["2 stock items are running low."], "last_day_close": "2026-10-18",
        }

        def fake(req, timeout):
            if "100.64.0.10" in req.full_url:
                raise urllib.error.URLError("down")
            self.assertEqual(req.get_header("Authorization"), "Bearer k1")
            return FakeResponse(json.dumps(remote).encode())

        self.client.login(username="boss", password=PASSWORD)
        with mock.patch("urllib.request.urlopen", side_effect=fake):
            r = self.client.get(reverse("core:group"))
        self.assertContains(r, "Bar Blloku")
        self.assertContains(r, "2 stock items are running low.")
        self.assertContains(r, "Villa Sarandë")
        self.assertEqual(r.context["totals"]["€"]["sales_today"], D("250.00"))  # this one has no sales, the other is down
        self.assertIsNotNone(GroupMember.objects.get(name="Bar Blloku").last_ok_at)
        self.assertIsNone(GroupMember.objects.get(name="Villa Sarandë").last_ok_at)

    def test_wrong_key_message(self):
        m = GroupMember.objects.create(name="X", url="http://100.64.0.9:8765", token="bad")
        err = urllib.error.HTTPError(m.url, 403, "Forbidden", {}, None)
        from django.utils import translation

        with mock.patch("urllib.request.urlopen", side_effect=err), translation.override("en"):
            self.assertIn("key", group.fetch(m)["error"])

    def test_add_member_strips_the_path_and_only_managers(self):
        self.client.login(username="desk", password=PASSWORD)
        self.assertNotEqual(self.client.get(reverse("core:group")).status_code, 200)
        self.client.login(username="boss", password=PASSWORD)
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("x")):
            self.client.post(reverse("core:group_add"), {"name": "Bar", "url": "http://100.64.0.9:8765/group/summary/", "token": "k", "sort_order": 0})
        self.assertEqual(GroupMember.objects.get().url, "http://100.64.0.9:8765")
        self.assertContains(self.client.get("/"), reverse("core:group"))

    def test_settings_tab(self):
        self.share()
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.get(reverse("core:settings") + "?tab=group")
        self.assertContains(r, HotelSettings.load().group_token)

    def test_connection_banner_is_on_every_page(self):
        self.client.login(username="boss", password=PASSWORD)
        self.assertContains(self.client.get("/"), 'id="conn-banner"')
