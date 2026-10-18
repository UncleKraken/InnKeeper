import json
import sys
import threading
from pathlib import Path
from unittest import mock

from django.test import RequestFactory
from django.urls import reverse

from apps.core import remote
from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import PASSWORD, HotelTestCase


class RemoteHelpersTests(HotelTestCase):
    def test_addresses(self):
        addrs = ["192.168.1.20", "100.101.5.7", "10.0.0.3"]
        self.assertEqual(remote.tailscale_address(addrs), "100.101.5.7")
        self.assertEqual(remote.lan_address(addrs), "192.168.1.20")
        self.assertEqual(remote.tailscale_address(["192.168.1.20"]), "")

    def test_local_request(self):
        rf = RequestFactory()
        self.assertTrue(remote.is_local_request(rf.get("/", REMOTE_ADDR="192.168.1.30")))
        self.assertTrue(remote.is_local_request(rf.get("/", REMOTE_ADDR="100.88.1.2")))
        self.assertTrue(remote.is_local_request(rf.get("/", REMOTE_ADDR="127.0.0.1")))
        self.assertFalse(remote.is_local_request(rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_CF_CONNECTING_IP="8.8.8.8")))
        self.assertFalse(remote.is_local_request(rf.get("/", REMOTE_ADDR="81.26.200.10")))

    def test_pin_pad_refused_through_the_tunnel(self):
        self.waiter.set_pin("4826")
        self.waiter.save()
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("accounts:shared_till"), {"on": "1"})
        self.client.post(reverse("accounts:lock"))
        r = self.client.get(reverse("accounts:pin_pad"), HTTP_CF_CONNECTING_IP="8.8.8.8")
        self.assertTrue(r["Location"].startswith("/accounts/login/?password=1"))
        r = self.client.post(reverse("accounts:pin_pad"), {"user": self.waiter.pk, "pin": "4826"}, HTTP_CF_CONNECTING_IP="8.8.8.8")
        self.assertNotIn("_auth_user_id", self.client.session)
        r = self.client.post(reverse("accounts:pin_pad"), {"user": self.waiter.pk, "pin": "4826"})
        self.assertIn("_auth_user_id", self.client.session)

    def test_settings_page_and_token_cleaning(self):
        self.client.login(username="boss", password=PASSWORD)
        with mock.patch.object(remote, "local_addresses", return_value=["192.168.1.20", "100.101.5.7"]), \
             mock.patch.dict("os.environ", {"INNKEEPER_WINDOWS_APP": "1"}):
            page = self.client.get(reverse("core:settings") + "?tab=remote")
            self.assertContains(page, "http://100.101.5.7:")
            self.assertContains(page, "http://192.168.1.20:")
            token = "eyJ" + "a" * 150
            self.client.post(reverse("core:settings") + "?tab=remote", {"tunnel_enabled": "on", "tunnel_token": f"cloudflared.exe service install {token}"})
        hs = HotelSettings.objects.get()
        self.assertEqual((hs.tunnel_enabled, hs.tunnel_token), (True, token))
        self.client.post(reverse("core:settings") + "?tab=remote", {"tunnel_enabled": "on", "tunnel_token": "short"})
        self.assertEqual(HotelSettings.objects.get().tunnel_token, token)

    def test_status_file(self):
        with mock.patch.object(remote, "data_dir", return_value=Path(self._tmp())):
            self.assertEqual(remote.read_status()["state"], "off")
            remote.write_status("running")
            self.assertEqual(remote.read_status()["state"], "running")
            data = json.loads(remote.status_file().read_text())
            data["at"] -= 600
            remote.status_file().write_text(json.dumps(data))
            self.assertEqual(remote.read_status()["state"], "unknown")

    def _tmp(self):
        import tempfile

        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d


class LauncherTunnelTests(HotelTestCase):
    def test_tunnel_started_with_token_in_environment_and_stopped(self):
        import tempfile

        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "windows"))
        import launcher

        tmp = Path(tempfile.mkdtemp())
        exe = tmp / "bin" / "cloudflared.exe"
        exe.parent.mkdir()
        exe.write_bytes(b"MZ")
        HotelSettings.objects.update(tunnel_enabled=True, tunnel_token="t" * 120)
        clear_settings_cache()
        stop = threading.Event()
        fake = mock.MagicMock()
        fake.poll.return_value = None

        def popen(args, **kw):
            self.assertNotIn("t" * 120, " ".join(args))
            self.assertEqual(kw["env"]["TUNNEL_TOKEN"], "t" * 120)
            stop.set()
            return fake

        with mock.patch.object(remote, "data_dir", return_value=tmp), \
             mock.patch("subprocess.Popen", side_effect=popen), mock.patch("time.sleep"), \
             mock.patch("django.db.close_old_connections"):
            launcher.tunnel_jobs(lambda m: None, stop)
        fake.terminate.assert_called_once()
