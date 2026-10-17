import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core import backup, sync
from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import PASSWORD, HotelTestCase
from apps.frontdesk.models import Guest


class CopyTests(HotelTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.local = root / "InnKeeper-data" / "backups"  # like %LOCALAPPDATA%\\InnKeeper\\backups
        self.target = root / "usb" / "InnKeeper"
        o = override_settings(INNKEEPER_BACKUP_DIR=self.local)
        o.enable()
        self.addCleanup(o.disable)

    def configure(self, **extra):
        values = {"sync_enabled": True, "sync_folder": str(self.target), "sync_every": 60, **extra}
        HotelSettings.objects.update(**values)
        clear_settings_cache()

    def test_a_copy_is_written_checked_and_restorable(self):
        self.configure()
        path = sync.run(force=True)
        self.assertTrue(path.is_file() and path.parent == self.target)
        self.assertEqual(list(self.target.glob("*.part")), [])
        doc = backup.read_file(path.read_bytes())
        self.assertEqual(doc["kind"], "full")
        hs = HotelSettings.load()
        self.assertEqual((hs.sync_last_file, hs.sync_last_error), (path.name, ""))
        self.assertEqual(sync.status(hs)["state"], "ok")

    def test_password_protected_copy(self):
        self.configure(sync_password="kafe-2026")
        path = sync.run(force=True)
        raw = path.read_bytes()
        self.assertTrue(backup.is_encrypted(raw))
        self.assertNotIn(b"Ana", raw)
        with self.assertRaises(backup.BackupError):
            backup.read_file(raw)
        with self.assertRaises(backup.BackupError):
            backup.read_file(raw, "wrong")
        self.assertEqual(backup.read_file(raw, "kafe-2026")["kind"], "full")

        self.client.login(username="boss", password=PASSWORD)
        r = self.client.get(reverse("core:restore_from_copy") + f"?name={path.name}", follow=True)
        self.assertTemplateUsed(r, "core/restore_password.html")
        file = r.context["file"]
        r = self.client.post(reverse("core:restore"), {"file": file, "password": "wrong"})
        self.assertTrue(r.context["wrong"])
        r = self.client.post(reverse("core:restore"), {"file": file, "password": "kafe-2026"})
        self.assertTemplateUsed(r, "core/restore_confirm.html")
        self.assertEqual(r.context["summary"]["kind"], "full")

    def test_unchanged_data_is_not_copied_again_until_the_next_day(self):
        self.configure(sync_every=15)
        sync.run(force=True)
        HotelSettings.objects.update(sync_last_at=timezone.now() - timedelta(hours=1))
        clear_settings_cache()
        self.assertIsNone(sync.run())
        self.assertEqual(len(list(self.target.glob("*.innkeeper"))), 1)
        Guest.objects.create(first_name="New", last_name="Guest")
        HotelSettings.objects.update(sync_last_at=timezone.now() - timedelta(hours=1))
        clear_settings_cache()
        self.assertIsNotNone(sync.run())

    def test_not_due_yet(self):
        self.configure(sync_every=60)
        sync.run(force=True)
        self.assertFalse(sync.due(HotelSettings.load()))
        self.assertTrue(sync.due(HotelSettings.load(), now=timezone.now() + timedelta(minutes=61)))

    def test_a_missing_drive_is_reported_and_retried_later(self):
        blocker = Path(self._tmp.name) / "not-a-folder"
        blocker.write_text("x")
        self.configure(sync_folder=str(blocker / "InnKeeper"))
        self.assertIsNone(sync.run())
        hs = HotelSettings.load()
        self.assertTrue(hs.sync_last_error)
        self.assertEqual(sync.status(hs)["state"], "failing")
        self.assertFalse(sync.due(hs))  # waits a few minutes before trying again
        self.client.login(username="boss", password=PASSWORD)
        self.assertContains(self.client.get(reverse("core:dashboard")), "#sync")
        with self.assertRaises(sync.SyncError):
            sync.run(force=True)

    def test_old_copies_are_thinned_out(self):
        self.target.mkdir(parents=True)
        now = datetime(2026, 10, 17, 12, 0)
        stamps = [now - timedelta(hours=h) for h in range(0, 48, 4)]  # last two days: all kept
        stamps += [now - timedelta(days=d, hours=h) for d in range(3, 10) for h in (1, 5)]  # two a day: one kept
        stamps += [now - timedelta(days=d) for d in (100, 105, 140)]  # old: one per month (100 and 105 days: both July)
        for s in stamps:
            (self.target / f"InnKeeper-{s:%Y-%m-%d_%H%M%S}.innkeeper").write_bytes(b"x")
        (self.target / "notes.txt").write_text("mine")
        sync.prune(self.target, now=now)
        left = sorted(p.name for p in self.target.glob("InnKeeper-*"))
        self.assertEqual(len(left), 12 + 7 + 2)
        self.assertTrue((self.target / "notes.txt").exists())

    def test_settings_form(self):
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.post(
            reverse("core:sync_settings"),
            {"sync_enabled": "on", "sync_folder": str(self.local / "inside"), "sync_every": "60", "sync_password": ""},
        )
        self.assertIn("sync_folder", r.context["sync_form"].errors)  # not inside InnKeeper's own folder
        r = self.client.post(
            reverse("core:sync_settings"),
            {"sync_enabled": "on", "sync_folder": str(self.target), "sync_every": "60", "sync_password": ""},
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(list(self.target.glob("*.innkeeper"))), 1)  # first copy made straight away
        page = self.client.get(reverse("core:settings") + "?tab=backup")
        self.assertEqual(len(page.context["sync_copies"]), 1)

    def test_settings_export_leaves_the_copy_settings_on_this_computer(self):
        self.configure(sync_password="secret-pw")
        doc = backup.read_file(backup.export_settings())
        self.assertNotIn("sync_password", doc["data"]["hotel"])
        self.assertNotIn("sync_folder", doc["data"]["hotel"])
