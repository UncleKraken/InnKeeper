"""
Shared tills: staff switch with their name and a short PIN instead of a username and password.

Only a device a manager has marked as a shared till shows the PIN pad (a signed cookie, so it can't be
forged). Each person picks their name and types their PIN; five wrong PINs lock that person on that
device for 15 minutes. After a few minutes without a tap the till locks itself again.
"""

import re
from urllib.parse import quote

from django import forms
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.core.forms import StyledFormMixin
from apps.core.models import audit

from .forms import LOCKOUT_SECONDS, MAX_FAILED_LOGINS, _client_ip
from .models import User
from .permissions import module_required

COOKIE = "innkeeper_till"
COOKIE_SALT = "innkeeper.shared-till"
COOKIE_AGE = 5 * 365 * 24 * 3600
WEAK = {"0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999", "1234", "4321", "1212", "0123"}


def is_shared_till(request) -> bool:
    return request.get_signed_cookie(COOKIE, default="", salt=COOKIE_SALT) == "1"


def check_pin_strength(pin: str) -> str | None:
    if not re.fullmatch(r"\d{4,6}", pin or ""):
        return _("Use 4 to 6 digits.")
    if pin in WEAK or len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210":
        return _("This PIN is too easy to guess. Choose another.")
    return None


class PinForm(StyledFormMixin, forms.Form):
    pin1 = forms.CharField(
        label=gettext_lazy("New PIN"),
        widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off", "maxlength": 6}),
    )
    pin2 = forms.CharField(
        label=gettext_lazy("Repeat the PIN"),
        widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off", "maxlength": 6}),
    )

    def __init__(self, *args, ask_password_for=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = ask_password_for
        if ask_password_for is not None:
            self.fields = {
                "password": forms.CharField(
                    label=gettext_lazy("Your password"), widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
                ),
                **self.fields,
            }
            self.fields["password"].widget.attrs.setdefault("class", "input")

    def clean(self):
        cleaned = super().clean()
        if self.user is not None and not self.user.check_password(cleaned.get("password") or ""):
            self.add_error("password", _("Wrong password."))
        p1, p2 = cleaned.get("pin1") or "", cleaned.get("pin2") or ""
        problem = check_pin_strength(p1)
        if problem:
            self.add_error("pin1", problem)
        elif p1 != p2:
            self.add_error("pin2", _("The PINs do not match."))
        return cleaned


@login_required
def my_pin(request):
    form = PinForm(request.POST or None, ask_password_for=request.user)
    if request.method == "POST":
        if request.POST.get("remove") == "1":
            request.user.set_pin("")
            request.user.save(update_fields=["pin"])
            audit(request.user, "auth.pin_removed", str(request.user), request.user)
            messages.success(request, _("Your PIN was removed."))
            return redirect("accounts:my_pin")
        if form.is_valid():
            request.user.set_pin(form.cleaned_data["pin1"])
            request.user.save(update_fields=["pin"])
            audit(request.user, "auth.pin_set", str(request.user), request.user)
            messages.success(request, _("Your PIN is set. Use it on shared tills."))
            return redirect("accounts:my_pin")
    return render(request, "accounts/pin_form.html", {"form": form, "who": request.user, "own": True})


@module_required("management")
def staff_set_pin(request, pk):
    staff = get_object_or_404(User, pk=pk)
    form = PinForm(request.POST or None)
    if request.method == "POST":
        if request.POST.get("remove") == "1":
            staff.set_pin("")
            staff.save(update_fields=["pin"])
            audit(request.user, "staff.pin_removed", str(staff), staff)
            messages.success(request, _("PIN removed for %(name)s.") % {"name": staff})
            return redirect("accounts:staff_edit", pk=staff.pk)
        if form.is_valid():
            staff.set_pin(form.cleaned_data["pin1"])
            staff.save(update_fields=["pin"])
            audit(request.user, "staff.pin_set", str(staff), staff)
            messages.success(request, _("PIN set for %(name)s. Tell them in person.") % {"name": staff})
            return redirect("accounts:staff_edit", pk=staff.pk)
    return render(request, "accounts/pin_form.html", {"form": form, "who": staff, "own": False})


@require_POST
@module_required("management")
def shared_till(request):
    """Mark (or unmark) the device this browser runs on as a shared till."""
    response = redirect("/settings/?tab=tills")
    if request.POST.get("on") == "1":
        response.set_signed_cookie(
            COOKIE, "1", salt=COOKIE_SALT, max_age=COOKIE_AGE, httponly=True, samesite="Lax", secure=request.is_secure()
        )
        audit(request.user, "till.shared_on", request.META.get("HTTP_USER_AGENT", "")[:120])
        messages.success(request, _("This device is now a shared till. Staff sign in with their name and PIN."))
    else:
        response.delete_cookie(COOKIE)
        audit(request.user, "till.shared_off", request.META.get("HTTP_USER_AGENT", "")[:120])
        messages.success(request, _("This device is a normal device again."))
    return response


def _fail_key(request, user_id) -> str:
    return f"innkeeper:pin-fail:{user_id}:{_client_ip(request)}"


def _safe_next(request) -> str:
    nxt = request.POST.get("next") or request.GET.get("next") or "/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return "/"
    return nxt


def pin_pad(request):
    """The lock screen of a shared till: tap your name, type your PIN."""
    if not is_shared_till(request):
        return redirect("accounts:login")
    from apps.core.remote import is_local_request

    if not is_local_request(request):  # a PIN is short: never accept one from the internet
        from urllib.parse import quote

        return redirect(f"/accounts/login/?password=1&next={quote(_safe_next(request))}")
    staff = list(User.objects.filter(is_active=True).exclude(pin="").order_by("first_name", "username"))
    error = ""
    done = ""
    chosen = None
    if request.method == "POST":
        chosen = next((u for u in staff if str(u.pk) == request.POST.get("user")), None)
        key = _fail_key(request, chosen.pk if chosen else 0)
        if chosen is None:
            error = _("Tap your name first.")
        elif cache.get(key, 0) >= MAX_FAILED_LOGINS:
            error = _("Too many wrong PINs. Try again in 15 minutes or ask a manager.")
        elif chosen.check_pin(request.POST.get("pin", "")) and request.POST.get("action") == "clock":
            # Clock in or out only: nobody is signed in, the pad stays for the next person.
            cache.delete(key)
            from apps.core.exceptions import BusinessError
            from apps.staff import services as staff_services
            from apps.staff.models import TimeEntry

            try:
                direction, entry = staff_services.toggle(chosen, source=TimeEntry.Source.PIN)
            except BusinessError as e:
                error = str(e)
            else:
                from django.utils import timezone

                if direction == "in":
                    done = _("%(name)s clocked in at %(t)s.") % {"name": chosen.first_name or chosen, "t": timezone.localtime(entry.clock_in).strftime("%H:%M")}
                else:
                    done = _("%(name)s clocked out at %(t)s: %(h)s hours.") % {
                        "name": chosen.first_name or chosen, "t": timezone.localtime(entry.clock_out).strftime("%H:%M"), "h": entry.hours}
            chosen = None
        elif chosen.check_pin(request.POST.get("pin", "")):
            cache.delete(key)
            if request.user.is_authenticated and request.user.pk != chosen.pk:
                logout(request)
            login(request, chosen, backend="django.contrib.auth.backends.ModelBackend")
            request.session["pin_login"] = True
            audit(chosen, "auth.pin_login", str(chosen), chosen)
            # Back to where the till was locked only for the same person; the next one starts at their home.
            same = (request.POST.get("by") or request.GET.get("by")) == str(chosen.pk)
            return redirect(_safe_next(request) if same or not (request.POST.get("by") or request.GET.get("by")) else "/")
        else:
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, LOCKOUT_SECONDS)
            error = _("Wrong PIN.")
    return render(
        request,
        "accounts/pin_pad.html",
        {
            "staff": staff,
            "error": error,
            "done": done,
            "chosen": chosen,
            "clocked": _clocked_ids(),
            "mode": "clock" if request.POST.get("action") == "clock" or request.GET.get("mode") == "clock" else "signin",
            "next": _safe_next(request),
            "by": request.POST.get("by") or request.GET.get("by", ""),
        },
    )


@require_POST
def lock(request):
    """Lock a shared till: sign out and show the PIN pad (a normal device just signs out)."""
    nxt = _safe_next(request)
    by = ""
    if request.user.is_authenticated:
        by = str(request.user.pk)
        audit(request.user, "auth.lock", str(request.user))
    logout(request)
    if is_shared_till(request):
        return redirect(f"/accounts/pin/?next={quote(nxt)}&by={by}")
    return redirect("accounts:login")


def _clocked_ids() -> set[int]:
    from apps.staff.models import TimeEntry

    return set(TimeEntry.objects.filter(clock_out__isnull=True).values_list("user_id", flat=True))
