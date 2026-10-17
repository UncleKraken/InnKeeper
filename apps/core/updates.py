"""Tell managers when a newer InnKeeper release exists on GitHub. Fails silently when offline."""

import json
import urllib.request

from django.conf import settings
from django.core.cache import cache

from apps import __version__

CACHE_KEY = "innkeeper:latest-release"
CHECK_EVERY = 12 * 3600


def _parse(version: str) -> tuple[int, ...]:
    parts = []
    for piece in version.lstrip("vV").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def latest_release() -> dict | None:
    repo = getattr(settings, "INNKEEPER_UPDATE_REPO", "")
    if not repo:
        return None
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached or None
    info: dict = {}
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": f"InnKeeper/{__version__}"},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.load(resp)
        info = {
            "version": data.get("tag_name", ""),
            "url": data.get("html_url", ""),
            "notes": (data.get("body") or "")[:6000],
        }
        for asset in data.get("assets") or []:
            name = asset.get("name", "")
            if name.lower().startswith("innkeeper-setup") and name.lower().endswith(".exe"):
                info["installer"] = {
                    "name": name,
                    "url": asset.get("browser_download_url", ""),
                    "size": asset.get("size") or 0,
                    "sha256": (asset.get("digest") or "").removeprefix("sha256:"),
                }
    except Exception:
        info = {}
    cache.set(CACHE_KEY, info, CHECK_EVERY)
    return info or None


def update_available() -> dict | None:
    info = latest_release()
    if info and info.get("version") and _parse(info["version"]) > _parse(__version__):
        return info
    return None


# ---------- Installing an update (Windows app) ----------
#
# Download the new installer from the GitHub release, check its size and SHA-256 (GitHub publishes
# the digest of every release file), save a backup and a copy to the other place, then start the
# installer silently and close InnKeeper so its files can be replaced. The installer starts
# InnKeeper again when it is done; the browser page waits and reloads.

import hashlib  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
from pathlib import Path  # noqa: E402

log = logging.getLogger(__name__)
ALLOWED_HOSTS = ("https://github.com/", "https://objects.githubusercontent.com/", "https://release-assets.githubusercontent.com/")
STATE: dict = {"state": "idle"}
_lock = threading.Lock()


def can_install() -> bool:
    """Only the Windows app installs updates by itself."""
    return bool(getattr(settings, "INNKEEPER_WINDOWS_APP", False)) and os.name == "nt"


def start_install(info: dict) -> bool:
    with _lock:
        if STATE.get("state") in ("downloading", "installing"):
            return False
        STATE.clear()
        STATE.update({"state": "downloading", "percent": 0, "version": info.get("version", "")})
    threading.Thread(target=_install, args=(info,), daemon=True).start()
    return True


def _install(info: dict) -> None:
    try:
        exe = download(info["installer"])
        STATE.update(state="backing-up")
        _backup_first()
        STATE.update(state="installing")
        _run_installer(exe)
    except Exception as e:  # shown on the update page; InnKeeper keeps running on the old version
        log.exception("Update failed")
        STATE.update(state="error", message=str(e)[:300])


def download(asset: dict, folder: Path | None = None) -> Path:
    url = asset.get("url", "")
    if not url.startswith(ALLOWED_HOSTS):
        raise ValueError("The installer is not on GitHub.")
    folder = folder or Path(settings.INNKEEPER_BACKUP_DIR).parent / "updates"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / os.path.basename(asset["name"])
    part = target.with_suffix(".part")
    digest = hashlib.sha256()
    done = 0
    req = urllib.request.Request(url, headers={"User-Agent": f"InnKeeper/{__version__}"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(part, "wb") as f:
        total = asset.get("size") or int(resp.headers.get("Content-Length") or 0)
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if total:
                STATE["percent"] = min(99, done * 100 // total)
    if asset.get("size") and done != asset["size"]:
        part.unlink(missing_ok=True)
        raise ValueError("The download was incomplete. Try again.")
    if asset.get("sha256") and digest.hexdigest() != asset["sha256"].lower():
        part.unlink(missing_ok=True)
        raise ValueError("The downloaded installer failed its safety check (SHA-256). It was deleted.")
    os.replace(part, target)
    STATE["percent"] = 100
    return target


def _backup_first() -> None:
    from . import backup, sync

    backup.save_backup_to_disk(f"before-update-{__version__}", keep=5)
    try:
        sync.run(if_changed=True)
    except Exception:
        log.warning("Copy before update failed", exc_info=True)


def _run_installer(exe: Path) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [str(exe), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
        creationflags=flags,
        close_fds=True,
    )
    # Give the page a moment to see "installing", then step aside so the files can be replaced.
    threading.Timer(4.0, lambda: os._exit(0)).start()
