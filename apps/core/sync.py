"""
Automatic copies of all data to another place.

The other place is a folder: a USB drive, a network drive, or a folder that OneDrive, Google Drive
or Dropbox keeps in the cloud. Using the cloud provider's own folder means no accounts or keys in
InnKeeper, and it keeps working offline (the provider uploads when the internet is back).

Every copy is a complete full backup. It is written as `<name>.part`, flushed to disk, read back
and checked (decrypted and parsed when it has a password), and only then renamed, so the folder
never holds a half-written copy. Old copies are thinned out: everything from the last two days,
one per day for two months, one per month after that.
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from django.utils import timezone
from django.utils.translation import gettext as _

from . import backup
from .models import HotelSettings

log = logging.getLogger(__name__)

PREFIX = "InnKeeper-"
SUFFIX = ".innkeeper"
STAMP = "%Y-%m-%d_%H%M%S"
RETRY_AFTER = timedelta(minutes=5)  # after a failure (e.g. the USB drive is out), don't retry every minute
SAME_DATA_EVERY = timedelta(hours=24)  # an unchanged business still gets one fresh copy a day


class SyncError(Exception):
    pass


def check_folder(value: str) -> str | None:
    """A problem with the folder, in words for the manager, or None when copies can be written there."""
    value = (value or "").strip()
    if not value:
        return _("Choose a folder.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        return _("Use a full path, for example E:\\InnKeeper or C:\\Users\\Name\\OneDrive\\InnKeeper.")
    if _inside(path, backup.backup_dir().resolve().parent):
        return _("Choose a folder outside InnKeeper's own data: the point is a second place.")
    anchor = Path(path.anchor) if path.anchor else None
    if anchor and not anchor.exists():
        return _("The drive %(d)s is not connected.") % {"d": path.anchor}
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".innkeeper-write-test"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as e:
        return _("InnKeeper can't write there: %(e)s") % {"e": e.strerror or e}
    return None


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent)
        return True
    except (ValueError, OSError):
        return False


def due(hs: HotelSettings, now=None) -> bool:
    if not (hs.sync_enabled and hs.sync_folder):
        return False
    now = now or timezone.now()
    if hs.sync_last_error_at and (not hs.sync_last_at or hs.sync_last_error_at > hs.sync_last_at):
        if now - hs.sync_last_error_at < RETRY_AFTER:
            return False
    return not hs.sync_last_at or now - hs.sync_last_at >= timedelta(minutes=hs.sync_every)


def run(force: bool = False, if_changed: bool = False) -> Path | None:
    """Write a copy if one is due (or `force`). `if_changed` writes one now, but only if the data
    changed since the last copy (used when InnKeeper is stopped). Returns the new file or None."""
    hs = HotelSettings.load()
    if not (hs.sync_enabled and hs.sync_folder):
        if force:
            raise SyncError(_("Automatic copies are not switched on."))
        return None
    if not force and not if_changed and not due(hs):
        return None
    try:
        problem = check_folder(hs.sync_folder)  # first: no point exporting when the USB drive is out
        if problem:
            raise SyncError(problem)
        raw, digest = backup.export_full_with_digest()
        now = timezone.now()
        if (
            not force
            and digest == hs.sync_last_digest
            and hs.sync_last_at
            and (if_changed or now - hs.sync_last_at < SAME_DATA_EVERY)
            and (Path(hs.sync_folder) / hs.sync_last_file).is_file()
        ):
            _record(sync_last_at=now)  # nothing changed since the last copy, which is still there
            return None
        path = _write(Path(hs.sync_folder).expanduser(), raw, hs.sync_password)
        prune(path.parent)
    except Exception as e:
        message = str(e) if isinstance(e, SyncError) else f"{type(e).__name__}: {e}"
        log.warning("Copy to %s failed: %s", hs.sync_folder, message)
        _record(sync_last_error=message[:500], sync_last_error_at=timezone.now())
        if force:
            raise SyncError(message) from e
        return None
    _record(sync_last_at=timezone.now(), sync_last_file=path.name, sync_last_digest=digest, sync_last_error="")
    log.info("Copy saved: %s", path)
    return path


def _write(folder: Path, raw: bytes, password: str) -> Path:
    data = backup.encrypt(raw, password) if password else raw
    name = f"{PREFIX}{timezone.localtime():{STAMP}}{SUFFIX}"
    final = folder / name
    part = folder / (name + ".part")
    with open(part, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    try:
        written = part.read_bytes()
        if written != data:
            raise SyncError(_("The copy read back differently from what was written. Check the drive."))
        backup.read_file(written, password or None)  # decrypts and parses: the copy can really be restored
        os.replace(part, final)
    finally:
        part.unlink(missing_ok=True)
    return final


def _record(**fields) -> None:
    """Save the job's status without touching anything else in the settings."""
    from .models import clear_settings_cache

    HotelSettings.objects.filter(pk=1).update(**fields)
    clear_settings_cache()


def copies(folder: str | Path | None = None, limit: int = 60) -> list[dict]:
    """The copies in the folder, newest first."""
    folder = Path(folder or HotelSettings.load().sync_folder or "")
    if not str(folder) or not folder.is_dir():
        return []
    out = []
    for f in sorted(folder.glob(f"{PREFIX}*{SUFFIX}"), reverse=True)[:limit]:
        try:
            with open(f, "rb") as fh:
                head = fh.read(len(backup.ENC_MAGIC))
            st = f.stat()
        except OSError:
            continue
        out.append(
            {
                "name": f.name,
                "size": st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime),
                "encrypted": head == backup.ENC_MAGIC,
            }
        )
    return out


def _stamp(name: str) -> datetime | None:
    try:
        return datetime.strptime(name[len(PREFIX) : -len(SUFFIX)], STAMP)
    except ValueError:
        return None


def prune(folder: Path, now: datetime | None = None) -> int:
    """Thin out old copies. Only InnKeeper's own copies are ever deleted."""
    now = now or datetime.now()
    files = [(f, _stamp(f.name)) for f in folder.glob(f"{PREFIX}*{SUFFIX}")]
    files = sorted(((f, s) for f, s in files if s), key=lambda x: x[1], reverse=True)
    keep: set[Path] = set()
    days: set = set()
    months: set = set()
    for f, s in files:
        age = now - s
        if age <= timedelta(days=2):
            keep.add(f)
        elif age <= timedelta(days=62):
            if s.date() not in days:
                days.add(s.date())
                keep.add(f)
        elif (s.year, s.month) not in months:
            months.add((s.year, s.month))
            keep.add(f)
    if files:
        keep.add(files[0][0])  # never delete the newest
    removed = 0
    for f, _s in files:
        if f not in keep:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def status(hs: HotelSettings | None = None, now=None) -> dict:
    """For the settings page and the dashboard: off / ok / late / failing, with the last copy time."""
    hs = hs or HotelSettings.load()
    now = now or timezone.now()
    if not (hs.sync_enabled and hs.sync_folder):
        return {"state": "off"}
    failing = bool(hs.sync_last_error) and (not hs.sync_last_at or (hs.sync_last_error_at or now) >= hs.sync_last_at)
    allowed = max(timedelta(minutes=hs.sync_every * 2), timedelta(minutes=hs.sync_every + 60))
    if hs.sync_every >= 1440:
        allowed = timedelta(hours=26)
    late = not hs.sync_last_at or now - hs.sync_last_at > allowed
    state = "failing" if failing else ("late" if late and hs.sync_last_at else ("pending" if late else "ok"))
    return {"state": state, "last_at": hs.sync_last_at, "file": hs.sync_last_file, "error": hs.sync_last_error}


def suggestions() -> list[tuple[str, str]]:
    """Folders on this computer that make good targets: removable drives and cloud folders."""
    found: list[tuple[str, str]] = []
    home = Path.home()
    for env, label in (("OneDriveCommercial", "OneDrive"), ("OneDriveConsumer", "OneDrive"), ("OneDrive", "OneDrive")):
        value = os.environ.get(env)
        if value and Path(value).is_dir():
            found.append((label, str(Path(value) / "InnKeeper")))
    for path, label in (
        (home / "Google Drive" / "My Drive", "Google Drive"),
        (Path("G:/My Drive"), "Google Drive"),
        (home / "Dropbox", "Dropbox"),
        (home / "iCloudDrive", "iCloud Drive"),
    ):
        if path.is_dir():
            found.append((label, str(path / "InnKeeper")))
    if os.name == "nt":
        try:
            import ctypes
            import string

            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for i, letter in enumerate(string.ascii_uppercase):
                if mask & (1 << i) and ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\") in (2, 4):  # removable, network
                    found.append((_("Drive %(d)s:") % {"d": letter}, f"{letter}:\\InnKeeper"))
        except Exception:
            pass
    seen, unique = set(), []
    for label, path in found:
        if path not in seen:
            seen.add(path)
            unique.append((label, path))
    return unique
