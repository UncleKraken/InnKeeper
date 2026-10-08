"""The public booking page (no login). Guests search dates, pick a room type, and send their details."""

from datetime import date, timedelta

from django import forms
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.core.exceptions import BusinessError
from apps.core.forms import StyledFormMixin
from apps.core.models import HotelSettings

from . import booking
from .models import Reservation, RoomType

MAX_BOOKINGS_PER_HOUR = 5


class SearchForm(forms.Form):
    arrival = forms.DateField(label=gettext_lazy("Arrival"))
    departure = forms.DateField(label=gettext_lazy("Departure"))
    adults = forms.IntegerField(label=gettext_lazy("Adults"), min_value=1, max_value=12, initial=2)
    children = forms.IntegerField(label=gettext_lazy("Children"), min_value=0, max_value=12, initial=0)

    def clean(self):
        cleaned = super().clean()
        a, d = cleaned.get("arrival"), cleaned.get("departure")
        if a and d:
            problem = booking.check_dates(a, d)
            if problem:
                raise forms.ValidationError(problem)
        return cleaned


class GuestForm(StyledFormMixin, forms.Form):
    first_name = forms.CharField(label=gettext_lazy("First name"), max_length=80)
    last_name = forms.CharField(label=gettext_lazy("Last name"), max_length=80)
    email = forms.EmailField(label=gettext_lazy("Email"))
    phone = forms.CharField(label=gettext_lazy("Phone"), max_length=40)
    nationality = forms.CharField(label=gettext_lazy("Country"), max_length=60, required=False)
    notes = forms.CharField(
        label=gettext_lazy("Requests"),
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=gettext_lazy("Arrival time, extra bed, airport transfer…"),
    )
    accept = forms.BooleanField(label=gettext_lazy("I accept the booking conditions"))
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("spam")
        return ""


def _lang(request) -> str:
    lang = request.GET.get("lang") or request.POST.get("lang") or translation.get_language() or "sq"
    lang = "en" if lang.startswith("en") else "sq"
    translation.activate(lang)
    return lang


def _require_open():
    if not HotelSettings.load().booking_open:
        raise Http404


def _client_key(request) -> str:
    from apps.core.middleware import client_ip

    return f"innkeeper:booking-ip:{client_ip(request)}"


def _type_name(rt: RoomType, lang: str) -> str:
    return rt.name_en if lang == "en" and rt.name_en else rt.name


def _type_description(rt: RoomType, lang: str) -> str:
    return rt.description_en if lang == "en" and rt.description_en else rt.description


@xframe_options_sameorigin
def search(request):
    _require_open()
    lang = _lang(request)
    today = timezone.localdate()
    first = today + timedelta(days=HotelSettings.load().booking_min_days_ahead)
    form = SearchForm(request.GET or None, initial={"arrival": first, "departure": first + timedelta(days=2)})
    offers = None
    if request.GET and form.is_valid():
        d = form.cleaned_data
        offers = [
            {
                "o": o,
                "name": _type_name(o.room_type, lang),
                "description": _type_description(o.room_type, lang),
            }
            for o in booking.search(d["arrival"], d["departure"], d["adults"], d["children"])
        ]
    return render(
        request,
        "booking/search.html",
        {"form": form, "offers": offers, "lang": lang, "min_date": first.isoformat(), "query": request.GET.urlencode()},
    )


def _parse_query(request):
    try:
        arrival = date.fromisoformat(request.GET.get("arrival", ""))
        departure = date.fromisoformat(request.GET.get("departure", ""))
        adults = max(1, int(request.GET.get("adults", "1")))
        children = max(0, int(request.GET.get("children", "0")))
    except ValueError:
        return None
    return arrival, departure, adults, children


@xframe_options_sameorigin
def details(request, type_id):
    _require_open()
    lang = _lang(request)
    room_type = get_object_or_404(RoomType, pk=type_id, is_active=True, bookable_online=True)
    parsed = _parse_query(request)
    if not parsed:
        return redirect("booking:search")
    arrival, departure, adults, children = parsed
    problem = booking.check_dates(arrival, departure)
    offer = next(
        (o for o in booking.search(arrival, departure, adults, children) if o.room_type.pk == room_type.pk), None
    )
    form = GuestForm(request.POST or None)
    error = problem or (None if offer and offer.bookable else _("This room is no longer available for these dates."))
    if request.method == "POST" and not error and form.is_valid():
        key = _client_key(request)
        if cache.get(key, 0) >= MAX_BOOKINGS_PER_HOUR:
            error = _("Too many bookings from this connection. Please call or email us.")
        else:
            try:
                res = booking.create_online_booking(
                    room_type,
                    arrival,
                    departure,
                    adults,
                    children,
                    {k: v.strip() if isinstance(v, str) else v for k, v in form.cleaned_data.items()},
                    language=lang,
                    base_url=request.build_absolute_uri("/"),
                )
            except BusinessError as e:
                error = str(e)
            else:
                try:
                    cache.incr(key)
                except ValueError:
                    cache.set(key, 1, 3600)
                return redirect(f"{booking.booking_url(res)}?lang={lang}")
    return render(
        request,
        "booking/details.html",
        {
            "form": form,
            "room_type": room_type,
            "name": _type_name(room_type, lang),
            "description": _type_description(room_type, lang),
            "offer": offer,
            "deposit": booking.deposit_for(offer.quote.total) if offer else 0,
            "arrival": arrival,
            "departure": departure,
            "adults": adults,
            "children": children,
            "error": error,
            "lang": lang,
            "query": request.GET.urlencode(),
        },
    )


@xframe_options_sameorigin
def status(request, token):
    if len(token) < 16:
        raise Http404
    res = get_object_or_404(Reservation.objects.select_related("guest", "room__room_type"), booking_token=token)
    lang = _lang(request)
    hs = HotelSettings.load()
    links = res.payment_links.filter(purpose="deposit")
    return render(
        request,
        "booking/status.html",
        {
            "r": res,
            "lang": lang,
            "name": _type_name(res.room.room_type, lang),
            "deposit_paid": links.filter(status="paid").exists(),
            "card_deposit": hs.payments_configured and hs.booking_card_deposit and res.status == res.Status.BOOKED,
        },
    )


@require_POST
def pay_deposit(request, token):
    """Guest pressed "Pay by card": reuse the open deposit link or make one, then go to the payment page."""
    from apps.payments import services as pay
    from apps.payments.models import PaymentLink

    res = get_object_or_404(Reservation, booking_token=token, status=Reservation.Status.BOOKED)
    lang = _lang(request)
    if not res.deposit_due or res.payment_links.filter(purpose="deposit", status="paid").exists():
        return redirect(f"{booking.booking_url(res)}?lang={lang}")
    link = res.payment_links.filter(purpose="deposit", status="pending", amount=res.deposit_due).first()
    try:
        link = link or pay.create_link(reservation=res, amount=res.deposit_due, purpose=PaymentLink.Purpose.DEPOSIT)
        return redirect(pay.start_checkout(link, request.build_absolute_uri("/"), lang))
    except BusinessError as e:
        from django.contrib import messages

        messages.error(request, str(e))
        return redirect(f"{booking.booking_url(res)}?lang={lang}")
