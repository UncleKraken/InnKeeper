"""
Online check-in: before arriving, the guest opens a private link (in the arrival email, on the booking
page or sent by WhatsApp) and enters their ID or passport details and those of everyone staying with them.
Reception sees it on the reservation, and the guest register lists every person, not only the main guest.

Reception can fill in the same details from the reservation page (Guests in this stay) for walk-ins.
"""

import secrets
from datetime import date

from django import forms
from django.contrib import messages
from django.core.cache import cache
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.cache import never_cache

from apps.accounts.permissions import module_required
from apps.core.forms import DateInput, StyledFormMixin
from apps.core.models import HotelSettings, audit

from .models import Guest, Reservation, StayGuest

MAX_PEOPLE = 12
MAX_POSTS_PER_HOUR = 20


# ---------- Links ----------


def ensure_token(res: Reservation) -> str:
    if not res.checkin_token:
        res.checkin_token = secrets.token_urlsafe(16)
        Reservation.objects.filter(pk=res.pk, checkin_token="").update(checkin_token=res.checkin_token)
        res.refresh_from_db(fields=["checkin_token"])
    return res.checkin_token


def link(res: Reservation, base_url: str = "") -> str:
    """The guest's link, or "" when there is no address the guest's phone can open."""
    base = (HotelSettings.load().public_url or base_url).rstrip("/")
    if not base:
        return ""
    return base + reverse("booking:checkin", args=[ensure_token(res)])


def offered(res: Reservation) -> bool:
    """Whether to offer the guest the online check-in (in emails, on the booking page)."""
    hs = HotelSettings.load()
    return bool(res.pk and hs.online_checkin and hs.public_url and res.status == Reservation.Status.BOOKED and res.departure > timezone.localdate())


def open_for_guest(res: Reservation) -> bool:
    return res.status == Reservation.Status.BOOKED and res.departure > timezone.localdate()


# ---------- Forms ----------


def _document_choices():
    return [("", "—")] + list(Guest.DocumentType.choices)


class PersonForm(StyledFormMixin, forms.Form):
    """One person. `strict` (the guest's own form) makes the identity details required for adults."""

    first_name = forms.CharField(label=gettext_lazy("First name"), max_length=80)
    last_name = forms.CharField(label=gettext_lazy("Last name"), max_length=80)
    nationality = forms.CharField(label=gettext_lazy("Nationality"), max_length=60, required=False)
    date_of_birth = forms.DateField(label=gettext_lazy("Date of birth"), required=False, widget=DateInput())
    document_type = forms.ChoiceField(label=gettext_lazy("Document type"), required=False, choices=_document_choices)
    document_number = forms.CharField(label=gettext_lazy("Document number"), max_length=60, required=False)

    def __init__(self, *args, strict: bool = False, child: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.child = child
        self.strict = strict
        if strict:
            self.fields["date_of_birth"].required = True
            if not child:
                for name in ("nationality", "document_type", "document_number"):
                    self.fields[name].required = True
        for name in ("nationality", "document_number"):
            self.fields[name].widget.attrs["autocomplete"] = "off"

    def clean_date_of_birth(self):
        d = self.cleaned_data.get("date_of_birth")
        if d and not (date(1900, 1, 1) <= d <= timezone.localdate()):
            raise forms.ValidationError(_("Check the date of birth."))
        return d

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("document_number") and not cleaned.get("document_type"):
            self.add_error("document_type", _("Choose the type of document."))
        return cleaned


class MainGuestForm(PersonForm):
    phone = forms.CharField(label=gettext_lazy("Phone"), max_length=40, required=False)
    email = forms.EmailField(label=gettext_lazy("Email"), required=False)
    address = forms.CharField(label=gettext_lazy("Home address"), max_length=255, required=False)
    arrival_time = forms.CharField(
        label=gettext_lazy("Expected arrival time"), max_length=20, required=False,
        help_text=gettext_lazy("For example 15:00 or “late evening”."),
    )


def build_forms(res: Reservation, data=None, *, strict: bool):
    """The main guest's form and one form per other person (adults first, then children)."""
    g = res.guest
    show_document = not strict or res.online_checkin_at is not None  # don't show stored ID numbers to a link alone
    main = MainGuestForm(
        data,
        prefix="g0",
        strict=strict,
        initial={
            "first_name": g.first_name, "last_name": g.last_name, "nationality": g.nationality,
            "date_of_birth": g.date_of_birth, "document_type": g.document_type if show_document else "",
            "document_number": g.document_number if show_document else "", "phone": g.phone, "email": g.email,
            "address": g.address, "arrival_time": res.arrival_time,
        },
    )
    existing_adults = [c for c in res.companions.all() if not c.is_child]
    existing_children = [c for c in res.companions.all() if c.is_child]
    others = []
    for i in range(min(max(res.adults - 1, 0), MAX_PEOPLE)):
        c = existing_adults[i] if i < len(existing_adults) else None
        form = _person_form(data, f"a{i + 1}", c, strict=strict, child=False, show_document=show_document)
        form.heading = _("Guest %(n)s") % {"n": i + 2}
        others.append(form)
    for i in range(min(res.children, MAX_PEOPLE)):
        c = existing_children[i] if i < len(existing_children) else None
        form = _person_form(data, f"c{i + 1}", c, strict=strict, child=True, show_document=show_document)
        form.heading = _("Child %(n)s") % {"n": i + 1}
        others.append(form)
    return main, others


def _person_form(data, prefix, c, *, strict, child, show_document):
    initial = {}
    if c:
        initial = {
            "first_name": c.first_name, "last_name": c.last_name, "nationality": c.nationality,
            "date_of_birth": c.date_of_birth,
            "document_type": c.document_type if show_document else "",
            "document_number": c.document_number if show_document else "",
        }
    form = PersonForm(data, prefix=prefix, strict=strict, child=child, initial=initial)
    if not strict:  # reception may leave a row empty and fill it in later
        for f in form.fields.values():
            f.required = False
    return form


def _blank(form) -> bool:
    return not any((form.cleaned_data.get(k) or "") for k in ("first_name", "last_name", "document_number"))


@transaction.atomic
def save(res: Reservation, main: MainGuestForm, others: list, *, by_guest: bool, user=None) -> None:
    g = res.guest
    d = main.cleaned_data
    for field in ("first_name", "last_name", "nationality", "date_of_birth", "document_type", "document_number", "address"):
        value = d.get(field)
        if value not in (None, ""):
            setattr(g, field, value.strip() if isinstance(value, str) else value)
    for field in ("phone", "email"):
        if d.get(field):
            setattr(g, field, d[field].strip())
    g.save()
    res.arrival_time = (d.get("arrival_time") or "").strip()
    fields = ["arrival_time"]
    if by_guest:
        res.online_checkin_at = timezone.now()
        fields.append("online_checkin_at")
    res.save(update_fields=fields)
    res.companions.all().delete()
    for form in others:
        c = form.cleaned_data
        if _blank(form):
            continue
        StayGuest.objects.create(
            reservation=res, is_child=form.child, first_name=(c.get("first_name") or "").strip(),
            last_name=(c.get("last_name") or "").strip(), nationality=(c.get("nationality") or "").strip(),
            date_of_birth=c.get("date_of_birth"), document_type=c.get("document_type") or "",
            document_number=(c.get("document_number") or "").strip(),
        )
    people = 1 + res.companions.count()
    if by_guest:
        audit(None, "reservation.online_checkin", f"{res.code} {g} ({people})", res)
    else:
        audit(user, "reservation.guests", f"{res.code} {g} ({people})", res)


# ---------- The guest's page (public) ----------


def _lang(request, res) -> str:
    from .guest_messages import language

    lang = request.GET.get("lang") or request.POST.get("lang") or language(res)
    lang = "en" if lang.startswith("en") else "sq"
    translation.activate(lang)
    return lang


@never_cache
def guest_page(request, token):
    if len(token) < 16 or not HotelSettings.load().online_checkin:
        raise Http404
    res = get_object_or_404(
        Reservation.objects.select_related("guest", "room__room_type").prefetch_related("companions"), checkin_token=token
    )
    if res.status not in (Reservation.Status.BOOKED, Reservation.Status.CHECKED_IN) or res.departure <= timezone.localdate():
        raise Http404
    lang = _lang(request, res)
    editable = open_for_guest(res)
    data = request.POST if request.method == "POST" and editable else None
    main, others = build_forms(res, data, strict=True)
    if data is not None:
        key = f"innkeeper:checkin-posts:{token}"
        if cache.get(key, 0) >= MAX_POSTS_PER_HOUR:
            messages.error(request, _("Too many attempts. Please try again later or contact us."))
        elif main.is_valid() and all(f.is_valid() for f in others):
            save(res, main, others, by_guest=True)
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, 3600)
            return redirect(f"{reverse('booking:checkin', args=[token])}?lang={lang}&done=1")
    from .public import _type_name

    return render(
        request,
        "booking/checkin.html",
        {
            "r": res, "lang": lang, "main": main, "others": others, "editable": editable,
            "done": request.GET.get("done") == "1" or (res.online_checkin_at and request.method == "GET" and not request.GET.get("edit")),
            "room_name": _type_name(res.room.room_type, lang),
        },
    )


# ---------- Reception: Guests in this stay ----------


@module_required("frontdesk")
def staff_page(request, pk):
    res = get_object_or_404(Reservation.objects.select_related("guest", "room").prefetch_related("companions"), pk=pk)
    if res.status in (Reservation.Status.CANCELLED, Reservation.Status.NO_SHOW):
        messages.error(request, _("Closed or cancelled reservations cannot be changed."))
        return redirect("frontdesk:reservation_detail", pk=pk)
    data = request.POST if request.method == "POST" else None
    main, others = build_forms(res, data, strict=False)
    if data is not None and main.is_valid() and all(f.is_valid() for f in others):
        save(res, main, others, by_guest=False, user=request.user)
        messages.success(request, _("Guest details saved."))
        return redirect("frontdesk:reservation_detail", pk=pk)
    return render(request, "frontdesk/stay_guests.html", {"r": res, "main": main, "others": others})
