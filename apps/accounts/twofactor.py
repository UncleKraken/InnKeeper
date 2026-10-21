"""
Two-step sign-in: after the password, a 6-digit code from an authenticator app on the phone
(Google Authenticator, Microsoft Authenticator, Authy, 2FAS…). Standard TOTP (RFC 6238): 30-second codes,
nothing is sent over the internet, and it works without signal.

If the phone is lost, one of the 8 recovery codes (shown once, when it is switched on) gets in instead,
and another manager can switch it off for that person under Staff.

PIN sign-in on a shared till stays as it is: PINs only work on the business's own network.
"""

import base64
import re
import hashlib
import hmac
import secrets
import struct
import time
from io import BytesIO
from urllib.parse import quote

from django import forms
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.models import HotelSettings, audit

from .models import User
from .permissions import module_required

STEP = 30
DIGITS = 6
WINDOW = 1  # also accept the code just before and just after (phone clocks drift)
PENDING = "innkeeper_two_step"  # session key while the password is checked but the code is not
PENDING_SECONDS = 300
MAX_TRIES = 5
RECOVERY_COUNT = 8


# ---------- Codes ----------


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def now_step(at: float | None = None) -> int:
    return int((at if at is not None else time.time()) // STEP)


def matching_step(secret: str, code: str, at: float | None = None) -> int | None:
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS or not secret:
        return None
    current = now_step(at)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def setup_uri(user: User, secret: str) -> str:
    issuer = f"InnKeeper {HotelSettings.load().name}".strip()
    label = quote(f"{issuer}:{user.username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP}"


def qr_svg(text: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    out = BytesIO()
    img.save(out)
    return out.getvalue().decode()


def _new_recovery_codes() -> tuple[list[str], list[str]]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    plain = ["".join(secrets.choice(alphabet) for _i in range(4)) + "-" + "".join(secrets.choice(alphabet) for _i in range(4)) for _n in range(RECOVERY_COUNT)]
    return plain, [make_password(c) for c in plain]


@transaction.atomic
def check(user: User, code: str) -> bool:
    """True for a fresh authenticator code or an unused recovery code (which is then used up)."""
    user = User.objects.select_for_update().get(pk=user.pk)
    step = matching_step(user.totp_secret, code)
    if step is not None:
        if step <= user.totp_last_step:  # already used: someone may have seen it
            return False
        user.totp_last_step = step
        user.save(update_fields=["totp_last_step"])
        return True
    cleaned = (code or "").strip().lower().replace(" ", "")
    if len(cleaned) == 8 and "-" not in cleaned:
        cleaned = cleaned[:4] + "-" + cleaned[4:]
    if not re.fullmatch(r"[a-z0-9]{4}-[a-z0-9]{4}", cleaned):
        return False
    for i, hashed in enumerate(user.recovery_codes):
        if check_password(cleaned, hashed):
            user.recovery_codes = user.recovery_codes[:i] + user.recovery_codes[i + 1:]
            user.save(update_fields=["recovery_codes"])
            audit(user, "auth.recovery_code", f"{user} ({len(user.recovery_codes)} left)", user)
            return True
    return False


def required_for(user) -> bool:
    return bool(getattr(user, "is_manager", False) and HotelSettings.load().require_two_step and not user.has_two_step)


# ---------- After the password ----------


def start_pending(request, user: User, backend: str, next_url: str) -> None:
    request.session[PENDING] = {"user": user.pk, "backend": backend, "next": next_url, "at": time.time()}


def _pending(request):
    data = request.session.get(PENDING)
    if not data or time.time() - data.get("at", 0) > PENDING_SECONDS:
        request.session.pop(PENDING, None)
        return None, None
    user = User.objects.filter(pk=data["user"], is_active=True).first()
    return user, data


class CodeForm(forms.Form):
    code = forms.CharField(max_length=20, widget=forms.TextInput(attrs={
        "class": "input", "inputmode": "numeric", "autocomplete": "one-time-code", "autofocus": True,
        "style": "font-size:1.6rem; letter-spacing:.3em; text-align:center",
    }))


def verify(request):
    user, data = _pending(request)
    if user is None:
        messages.info(request, _("Sign in again."))
        return redirect("accounts:login")
    form = CodeForm(request.POST or None)
    error = ""
    if request.method == "POST" and form.is_valid():
        key = f"innkeeper:two-step-tries:{user.pk}"
        tries = cache.get(key, 0)
        if tries >= MAX_TRIES:
            request.session.pop(PENDING, None)
            audit(user, "auth.two_step_locked", str(user), user)
            messages.error(request, _("Too many wrong codes. Sign in again in 15 minutes."))
            return redirect("accounts:login")
        if check(user, form.cleaned_data["code"]):
            cache.delete(key)
            request.session.pop(PENDING, None)
            login(request, user, backend=data["backend"])
            audit(user, "auth.login", f"{user} (two-step)")
            nxt = data.get("next") or "/"
            if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                nxt = "/"
            return redirect(nxt)
        cache.set(key, tries + 1, 900)
        error = _("Wrong code. Use the newest code in the app, or a recovery code.")
    return render(request, "accounts/two_step_verify.html", {"form": form, "error": error, "pending_user": user})


# ---------- Your account: switch it on or off ----------


class EnableForm(forms.Form):
    code = forms.CharField(max_length=10, widget=forms.TextInput(attrs={"class": "input", "inputmode": "numeric", "autocomplete": "one-time-code"}))


class PasswordConfirmForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "current-password"}))


@login_required
def manage(request):
    user = request.user
    recovery = request.session.pop("innkeeper_new_recovery", None)
    if user.has_two_step:
        return render(request, "accounts/two_step.html", {
            "on": True, "recovery": recovery, "left": len(user.recovery_codes), "password_form": PasswordConfirmForm(),
        })
    secret = request.session.get("innkeeper_new_totp") or new_secret()
    request.session["innkeeper_new_totp"] = secret
    form = EnableForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        step = matching_step(secret, form.cleaned_data["code"])
        if step is None:
            form.add_error("code", _("That code doesn't match. Check the phone's time and try the newest code."))
        else:
            plain, hashed = _new_recovery_codes()
            User.objects.filter(pk=user.pk).update(
                totp_secret=secret, totp_enabled_at=timezone.now(), totp_last_step=step, recovery_codes=hashed
            )
            request.session.pop("innkeeper_new_totp", None)
            request.session["innkeeper_new_recovery"] = plain
            audit(user, "auth.two_step_on", str(user), user)
            messages.success(request, _("Two-step sign-in is on."))
            return redirect("accounts:two_step")
    uri = setup_uri(user, secret)
    return render(request, "accounts/two_step.html", {
        "on": False, "form": form, "qr": qr_svg(uri), "secret": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)),
        "required": required_for(user),
    })


def _switch_off(user: User, by) -> None:
    User.objects.filter(pk=user.pk).update(totp_secret="", totp_enabled_at=None, totp_last_step=0, recovery_codes=[])
    audit(by, "auth.two_step_off", str(user), user)


@require_POST
@login_required
def disable(request):
    form = PasswordConfirmForm(request.POST)
    if not form.is_valid() or not request.user.check_password(form.cleaned_data["password"]):
        messages.error(request, _("Wrong password."))
        return redirect("accounts:two_step")
    if request.user.is_manager and HotelSettings.load().require_two_step:
        messages.error(request, _("Managers must use two-step sign-in here. Another manager can change that in Settings → Shared tills & PINs."))
        return redirect("accounts:two_step")
    _switch_off(request.user, request.user)
    messages.success(request, _("Two-step sign-in is off."))
    return redirect("accounts:two_step")


@require_POST
@login_required
def new_recovery_codes(request):
    if not request.user.has_two_step:
        return redirect("accounts:two_step")
    plain, hashed = _new_recovery_codes()
    User.objects.filter(pk=request.user.pk).update(recovery_codes=hashed)
    request.session["innkeeper_new_recovery"] = plain
    audit(request.user, "auth.recovery_codes", str(request.user), request.user)
    return redirect("accounts:two_step")


@require_POST
@module_required("management")
def staff_reset(request, pk):
    """A manager switches it off for someone who lost their phone (they set it up again at next sign-in)."""
    staff = get_object_or_404(User, pk=pk)
    _switch_off(staff, request.user)
    messages.success(request, _("Two-step sign-in was switched off for %(name)s.") % {"name": staff})
    return redirect("accounts:staff_edit", pk=pk)


class RequireTwoStepMiddleware:
    """When managers must use two-step sign-in, a manager without it can only open the page that sets it up."""

    ALLOWED = ("/accounts/two-step/", "/accounts/logout/", "/accounts/language/", "/static/", "/health/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not request.path.startswith(self.ALLOWED) and required_for(user):
            if request.method == "GET":
                messages.warning(request, _("Set up two-step sign-in to continue: managers must use it here."))
            return redirect("accounts:two_step")
        return self.get_response(request)
