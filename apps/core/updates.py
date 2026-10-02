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
        info = {"version": data.get("tag_name", ""), "url": data.get("html_url", "")}
    except Exception:
        info = {}
    cache.set(CACHE_KEY, info, CHECK_EVERY)
    return info or None


def update_available() -> dict | None:
    info = latest_release()
    if info and info.get("version") and _parse(info["version"]) > _parse(__version__):
        return info
    return None
