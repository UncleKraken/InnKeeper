"""
End-to-end test on a real Windows machine (GitHub Actions, see .github/workflows/e2e-windows.yml).

1. Starts InnKeeper with the Windows launcher, as the installed app does.
2. Cloudflare Tunnel: switches it on with a wrong token and checks that InnKeeper downloads Cloudflare's
   program, starts it, reports the problem, and stops it when switched off.
3. A real public tunnel (Cloudflare "quick tunnel", no account needed) to this InnKeeper, then over the
   internet: sign in, open pages, check the cookies are Secure, check a PIN is refused from outside.
4. Sends a cash deposit and a receipt to the Albanian tax authority's TEST system with a made-up
   certificate, to see that the requests reach it and how it answers.

Prints a summary; exits 1 if a required check failed (the tax authority answer is informational).
"""

import http.cookiejar
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8795
LOCAL = f"http://127.0.0.1:{PORT}"
DATA = Path(tempfile.mkdtemp(prefix="innkeeper-e2e-"))
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "", required: bool = True) -> bool:
    RESULTS.append((name, ok if required else True, ("" if ok else "NOT OK ") + detail if not required else detail))
    print(("PASS " if ok else ("FAIL " if required else "INFO ")) + name + (f" — {detail}" if detail else ""), flush=True)
    return ok


def django_setup():
    os.environ["INNKEEPER_DATA_DIR"] = str(DATA)
    os.environ["INNKEEPER_PORT"] = str(PORT)
    sys.path.insert(0, str(ROOT / "windows"))
    sys.path.insert(0, str(ROOT))
    import launcher

    launcher.configure_environment(launcher.data_dir())
    import django

    django.setup()


def wait_for(fn, seconds: float, step: float = 2.0):
    end = time.time() + seconds
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(step)
    return None


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


class Browser:
    """A tiny cookie-keeping client, enough to sign in through the tunnel."""

    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.addheaders = [("User-Agent", "Mozilla/5.0 InnKeeper-e2e")]
        self.last_headers = {}

    def get(self, path: str):
        with self.opener.open(self.base + path, timeout=30) as r:
            self.last_headers = dict(r.headers)
            return r.status, r.geturl(), r.read().decode("utf-8", "replace")

    def post(self, path: str, data: dict, referer: str):
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(self.base + path, data=body, method="POST")
        req.add_header("Referer", self.base + referer)
        req.add_header("Origin", self.base)
        try:
            with self.opener.open(req, timeout=30) as r:
                return r.status, r.geturl(), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            server = e.headers.get("Server", "")
            words = re.sub(r"<[^>]+>", " ", text)
            return e.code, f"{e.code} from {server}: {' '.join(words.split())[:400]}", text

    def csrf(self) -> str:
        return next((c.value for c in self.jar if c.name == "csrftoken"), "")


def main() -> int:
    django_setup()
    from django.contrib.auth.hashers import make_password  # noqa: F401  (Django ready)

    from apps.accounts.models import Role, User
    from apps.core import remote, sample
    from apps.core.models import HotelSettings, clear_settings_cache

    # Database first (the launcher would do it too), then a manager and the sample business.
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=0)
    manager = User.objects.create_user("manager", password="E2e-long-password-77", role=Role.MANAGER, is_superuser=True)
    sample.load(manager)
    HotelSettings.objects.update(setup_completed=True)
    clear_settings_cache()

    # 1. Start InnKeeper like the desktop shortcut does.
    env = {**os.environ, "INNKEEPER_DATA_DIR": str(DATA), "INNKEEPER_PORT": str(PORT)}
    app_log = (DATA / "app-output.txt").open("w")
    app = subprocess.Popen(
        [sys.executable, str(ROOT / "windows" / "launcher.py")], env=env, cwd=str(ROOT), stdout=app_log, stderr=subprocess.STDOUT
    )
    started = wait_for(lambda: http_ok(LOCAL + "/health/"), 90)
    if not check("InnKeeper starts with the Windows launcher", bool(started)):
        app.kill()
        return summary()

    # 2. Cloudflare Tunnel with a wrong token.
    HotelSettings.objects.update(tunnel_enabled=True, tunnel_token="eyJ" + "x" * 150)
    exe = remote.cloudflared_path()
    downloaded = wait_for(lambda: exe.exists() and exe.stat().st_size > 5_000_000, 240, 3)
    check("Cloudflare's program is downloaded", bool(downloaded), str(exe))
    if downloaded:
        out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60)
        check("cloudflared runs on Windows", out.returncode == 0, (out.stdout or out.stderr).strip()[:120])
    state = wait_for(lambda: (s := remote.read_status())["state"] in ("error", "running") and s, 120, 3)
    check(
        "A wrong token is reported on the settings page",
        bool(state) and state["state"] == "error",
        json.dumps(state) if state else "no status",
    )
    HotelSettings.objects.update(tunnel_enabled=False, tunnel_token="")
    off = wait_for(lambda: remote.read_status()["state"] == "off", 90, 3)
    check("Switching the tunnel off stops it", bool(off))

    # 3. A real public tunnel to this InnKeeper (quick tunnel: random trycloudflare.com address).
    public = ""
    quick = None
    if exe.exists():
        log = DATA / "quick.log"
        quick = subprocess.Popen(
            [str(exe), "tunnel", "--no-autoupdate", "--url", f"http://localhost:{PORT}"],
            stdout=subprocess.DEVNULL,
            stderr=log.open("w"),
        )

        def find_url():
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", log.read_text(errors="ignore") if log.exists() else "")
            return m.group(0) if m else ""

        public = wait_for(find_url, 90, 2) or ""
        check("Public tunnel address", bool(public), public, required=False)
    if public:
        reachable = wait_for(lambda: http_ok(public + "/health/"), 120, 5)
        check("InnKeeper answers over the internet (https)", bool(reachable), public + "/health/")
        if reachable:
            b = Browser(public)
            status, url, html = b.get("/accounts/login/?password=1")
            check("Sign-in page over the tunnel", status == 200 and "csrfmiddlewaretoken" in html)
            status, url, html = b.post(
                "/accounts/login/?password=1",
                {"csrfmiddlewaretoken": b.csrf(), "username": "manager", "password": "E2e-long-password-77", "next": "/"},
                "/accounts/login/?password=1",
            )
            signed_in = status == 200 and "/accounts/login" not in url
            check("Signing in over the tunnel works (CSRF, https)", signed_in, url)
            if not signed_in:
                tail = (DATA / "app-output.txt").read_text(errors="ignore")[-3000:]
                _annotation("warning", "InnKeeper output", tail)
            secure = all(c.secure for c in b.jar if c.name in ("sessionid", "csrftoken"))
            check("Session cookies are Secure over https", secure)
            if signed_in:
                for path in ("/", "/settings/?tab=remote", "/finance/month/", "/outlets/", "/stock/menu-profit/"):
                    s, _u, _h = b.get(path)
                    check(f"Page over the tunnel: {path}", s == 200)
                # A shared till can't be unlocked with a PIN from outside.
                manager.refresh_from_db()
                manager.set_pin("4826")
                manager.save()
                b.get("/settings/?tab=tills")
                b.post("/accounts/shared-till/", {"csrfmiddlewaretoken": b.csrf(), "on": "1"}, "/settings/?tab=tills")
                b.post("/accounts/lock/", {"csrfmiddlewaretoken": b.csrf()}, "/")
                s, url, html = b.get("/accounts/pin/")
                check("PIN pad refused from the internet", "/accounts/login/" in url and "password=1" in url, url)
    if quick is not None:
        quick.terminate()

    # 4. The tax authority's test system, with a made-up certificate.
    fiscal_probe()

    app.terminate()
    try:
        app.wait(20)
    except subprocess.TimeoutExpired:
        app.kill()
    left = subprocess.run(["tasklist", "/FI", "IMAGENAME eq cloudflared.exe"], capture_output=True, text=True).stdout
    check("No cloudflared left running", "cloudflared.exe" not in left, required=False)
    return summary()


def fiscal_probe():
    """Probe the tax authority's TEST system with made-up certificates (informational)."""
    from decimal import Decimal

    from cryptography.x509.oid import NameOID

    from apps.core.models import HotelSettings, clear_settings_cache
    from apps.fiscal import cis
    from apps.fiscal.signing import Certificate

    variants = [
        ("name only", [(NameOID.COMMON_NAME, "InnKeeper e2e")]),
        ("serialNumber=NIPT", [(NameOID.COMMON_NAME, "InnKeeper e2e"), (NameOID.SERIAL_NUMBER, "L12345678A")]),
        ("organizationIdentifier=NIPT", [(NameOID.COMMON_NAME, "InnKeeper e2e"), (NameOID.ORGANIZATION_IDENTIFIER, "L12345678A")]),
        ("OU=NIPT", [(NameOID.COMMON_NAME, "InnKeeper e2e"), (NameOID.ORGANIZATIONAL_UNIT_NAME, "L12345678A")]),
    ]
    for label, attrs in variants:
        p12 = _make_p12(attrs)
        _configure_fiscal(p12)
        clear_settings_cache()
        hs = HotelSettings.load()
        c = Certificate.from_settings(hs)
        try:
            xml = cis.cash_deposit_request(
                nuis=hs.tax_id, tcr=hs.fiscal_tcr_code, operation="INITIAL", amount=Decimal("0.00"), when=cis.now_str(), cert=c
            )
            fcdc = cis.register_cash_deposit(xml, test=True)
            check(f"Tax authority test system, certificate {label}", True, f"ACCEPTED, FCDC {fcdc}", required=False)
        except cis.CISError as e:
            check(f"Tax authority test system, certificate {label}", True, f"fault {e.code}: {str(e)[:160]}", required=False)
        except cis.CISUnavailable as e:
            check("Tax authority test system reached", False, f"unreachable: {e}", required=False)
            return
        except Exception as e:  # informational only
            check(f"Tax authority probe ({label})", False, f"{type(e).__name__}: {e}", required=False)

    # A real sale through the till: InnKeeper signs it and sends it to the test system.
    try:
        from apps.accounts.models import User
        from apps.fiscal.models import FiscalDocument
        from apps.outlets import services as pos
        from apps.outlets.models import Item, Outlet

        user = User.objects.get(username="manager")
        bar = Outlet.objects.filter(kind="bar").first()
        order = pos.open_order(bar, user=user, label="E2E")
        pos.add_item(order, Item.objects.filter(category__outlet=bar).first(), user=user)
        pos.pay_order(order, method="cash", user=user)
        doc = FiscalDocument.objects.filter(order=order).first()
        if doc is None:
            check("Tax authority probe (receipt)", False, "no fiscal document was created", required=False)
        else:
            doc.refresh_from_db()
            check(
                "Tax authority test system (receipt from the till)",
                True,
                f"status {doc.status}; NSLF {doc.iic[:12]}…; answer: {(doc.last_error or doc.fic)[:200]}",
                required=False,
            )
    except Exception as e:
        check("Tax authority probe (receipt)", False, f"{type(e).__name__}: {e}", required=False)

    # The same with a company as the buyer (invoice to a company, NUIS).
    try:
        order = pos.open_order(bar, user=user, label="E2E company")
        pos.add_item(order, Item.objects.filter(category__outlet=bar).first(), user=user)
        order.buyer_name, order.buyer_nuis, order.buyer_town = "E2E sh.p.k.", "L12345678A", "Tiranë"
        order.save(update_fields=["buyer_name", "buyer_nuis", "buyer_town"])
        pos.pay_order(order, method="card", user=user)
        doc = FiscalDocument.objects.filter(order=order).first()
        ok = doc is not None and (doc.payload or {}).get("buyer", {}).get("IDNum") == "L12345678A"
        detail = f"status {doc.status}; answer: {(doc.last_error or doc.fic)[:200]}" if doc else "no fiscal document"
        check("Tax authority test system (invoice to a company)", ok, detail, required=False)
    except Exception as e:
        check("Tax authority probe (company)", False, f"{type(e).__name__}: {e}", required=False)


def _make_p12(attrs) -> bytes:
    from datetime import UTC, datetime, timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(oid, value) for oid, value in attrs])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30)).sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(b"e2e", key, cert, None, serialization.BestAvailableEncryption(b"pw"))


def _configure_fiscal(p12: bytes) -> None:
    import base64

    from apps.core.models import HotelSettings

    HotelSettings.objects.update(
        tax_id="L12345678A", legal_name="InnKeeper E2E sh.p.k.", address="Rruga Test 1", fiscal_town="Tiranë",
        fiscal_enabled=True, fiscal_test=True, fiscal_business_unit="aa111aa111", fiscal_tcr_code="bb222bb222",
        fiscal_software_code="cc333cc333", fiscal_operator_code="dd444dd444", fiscal_maintainer_code="ee555ee555",
        fiscal_certificate=base64.b64encode(p12).decode(), fiscal_certificate_password="pw", demo_data=False,
    )


def _annotation(level: str, title: str, text: str) -> None:
    """GitHub shows these on the run page and in its API (the full log isn't always reachable)."""
    text = text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::{level} title={title}::{text[:60000]}", flush=True)


def summary() -> int:
    print("\n==== SUMMARY ====")
    failed = [n for n, ok, _d in RESULTS if not ok]
    lines = [f"{'PASS' if ok else 'FAIL'}  {n}{(' — ' + d) if d else ''}" for n, ok, d in RESULTS]
    print("\n".join(lines))
    print(f"{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    _annotation("error" if failed else "notice", "e2e summary", "\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback

        _annotation("error", "e2e crashed", traceback.format_exc())
        summary()
        sys.exit(1)
