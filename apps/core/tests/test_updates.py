import hashlib
import io
import tempfile
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from apps import __version__
from apps.core import updates
from apps.core.testing import PASSWORD, HotelTestCase

PAYLOAD = b"MZ fake installer bytes" * 1000
ASSET = {
    "name": "InnKeeper-Setup-9.9.9.exe",
    "url": "https://github.com/UncleKraken/InnKeeper/releases/download/v9.9.9/InnKeeper-Setup-9.9.9.exe",
    "size": len(PAYLOAD),
    "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
}


class FakeResponse(io.BytesIO):
    headers = {"Content-Length": str(len(PAYLOAD))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class DownloadTests(HotelTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)

    def fetch(self, asset, body=PAYLOAD):
        with mock.patch.object(updates.urllib.request, "urlopen", return_value=FakeResponse(body)):
            return updates.download(asset, folder=self.folder)

    def test_a_good_download_is_kept(self):
        path = self.fetch(ASSET)
        self.assertEqual(path.read_bytes(), PAYLOAD)
        self.assertEqual(list(self.folder.glob("*.part")), [])

    def test_a_tampered_download_is_deleted(self):
        with self.assertRaises(ValueError):
            self.fetch(ASSET, body=PAYLOAD[:-1] + b"X")
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_an_incomplete_download_is_deleted(self):
        with self.assertRaises(ValueError):
            self.fetch(ASSET, body=PAYLOAD[:100])
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_only_github(self):
        with self.assertRaises(ValueError):
            self.fetch({**ASSET, "url": "https://evil.example/InnKeeper-Setup.exe"})


@override_settings(INNKEEPER_UPDATE_REPO="UncleKraken/InnKeeper")
class UpdatePageTests(HotelTestCase):
    def setUp(self):
        cache.set(updates.CACHE_KEY, {"version": "v99.0.0", "url": "https://github.com/x", "notes": "New things", "installer": ASSET})
        self.addCleanup(cache.delete, updates.CACHE_KEY)
        self.client.login(username="boss", password=PASSWORD)

    def test_page_and_banner(self):
        r = self.client.get(reverse("core:update"))
        self.assertContains(r, "New things")
        self.assertFalse(r.context["can_install"])  # not the Windows app here: link to the release page
        self.assertContains(self.client.get(reverse("core:dashboard")), reverse("core:update"))

    def test_install_only_in_the_windows_app(self):
        with mock.patch.object(updates, "start_install") as start:
            self.client.post(reverse("core:update_install"))
        start.assert_not_called()
        with mock.patch.object(updates, "can_install", return_value=True), mock.patch.object(
            updates, "start_install"
        ) as start:
            self.client.post(reverse("core:update_install"))
        start.assert_called_once()

    def test_staff_cannot_update(self):
        self.client.login(username="waiter", password=PASSWORD)
        self.assertEqual(self.client.post(reverse("core:update_install")).status_code, 403)

    def test_health_reports_the_version(self):
        self.assertEqual(self.client.get("/health/").json()["version"], __version__)
