"""
Reaching InnKeeper from outside the business.

Two ways, both free:

* Tailscale (recommended for the owner): a private network between the owner's phone and the
  InnKeeper computer. Nothing is opened to the internet; the phone opens http://100.x.y.z:8765.
* Cloudflare Tunnel (for online booking, card payments and channel managers, which need a public
  https address): the Windows app runs Cloudflare's `cloudflared` with the tunnel token pasted in
  Settings. Needs a free Cloudflare account and a domain name.

The tunnel itself is started and watched by the Windows launcher (see windows/launcher.py); this module
holds the shared pieces: where cloudflared lives, its status file and the network addresses to show.
"""

import ipaddress
import json
import os
import socket
import time
from pathlib import Path

CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def is_windows_app() -> bool:
    return os.environ.get("INNKEEPER_WINDOWS_APP") == "1"


def port() -> int:
    return int(os.environ.get("INNKEEPER_PORT", "8765"))


def data_dir() -> Path:
    from . import backup

    return backup.backup_dir().parent


def cloudflared_path() -> Path:
    return data_dir() / "bin" / "cloudflared.exe"


def status_file() -> Path:
    return data_dir() / "tunnel.json"


def write_status(state: str, message: str = "") -> None:
    try:
        status_file().write_text(json.dumps({"state": state, "message": message[:400], "at": time.time()}), encoding="utf-8")
    except OSError:
        pass


def read_status() -> dict:
    try:
        data = json.loads(status_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "off", "message": "", "at": 0}
    if data.get("state") == "running" and time.time() - data.get("at", 0) > 180:
        data["state"] = "unknown"  # the launcher stopped reporting (InnKeeper closed?)
    return data


def local_addresses() -> list[str]:
    """IPv4 addresses of this computer (not loopback)."""
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            found.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith("127."))


def tailscale_address(addresses: list[str] | None = None) -> str:
    for a in addresses if addresses is not None else local_addresses():
        try:
            if ipaddress.ip_address(a) in TAILSCALE_NET:
                return a
        except ValueError:
            continue
    return ""


def lan_address(addresses: list[str] | None = None) -> str:
    for a in addresses if addresses is not None else local_addresses():
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if ip.is_private and ip not in TAILSCALE_NET:
            return a
    return ""


def is_local_request(request) -> bool:
    """True for a device on the business's own network (or the owner's private Tailscale network),
    False for anything coming through the public tunnel or from a public address."""
    remote = request.META.get("REMOTE_ADDR", "")
    if remote in ("127.0.0.1", "::1"):
        # The tunnel connects from this computer too, but always says who the visitor is.
        return not (request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("HTTP_X_FORWARDED_FOR"))
    try:
        ip = ipaddress.ip_address(remote)
    except ValueError:
        return False
    return ip.is_private or ip in TAILSCALE_NET
