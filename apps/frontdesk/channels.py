"""Rooms & rates → Channels: connect each room's calendar with Booking.com, Airbnb and others."""

from django import forms
from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.forms import StyledFormMixin
from apps.core.models import HotelSettings, audit

from . import ical
from .models import CalendarFeed, Room
from .views import SETUP_TABS


class FeedForm(StyledFormMixin, forms.ModelForm):
    full_width_fields = ("url",)

    class Meta:
        model = CalendarFeed
        fields = ["room", "source", "url"]
        labels = {"source": gettext_lazy("Channel")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = Room.objects.filter(is_active=True).select_related("room_type")
        self.fields["source"].choices = [
            c for c in self.fields["source"].choices if c[0] in {"booking_com", "airbnb", "expedia", "agency", "other"}
        ]

    url = forms.CharField(
        label=gettext_lazy("Calendar link (iCal)"),
        max_length=500,
        help_text=gettext_lazy("The export link from the channel's calendar settings, usually ending in .ics."),
    )

    def clean_url(self):
        from django.core.validators import URLValidator

        url = self.cleaned_data["url"].strip()
        if url.lower().startswith("webcal://"):
            url = "https://" + url[len("webcal://") :]
        URLValidator(schemes=["http", "https"])(url)
        return url


def _sync_message(request, feed, result):
    if result.error:
        messages.error(request, _("%(feed)s: could not read the calendar (%(e)s).") % {"feed": feed, "e": result.error})
        return
    messages.success(
        request,
        _("%(feed)s: %(c)s new, %(u)s changed, %(x)s cancelled.")
        % {"feed": feed, "c": result.created, "u": result.updated, "x": result.cancelled},
    )
    if result.conflicts:
        messages.warning(
            request,
            _("%(n)s booking(s) could not be added because the room is already taken. See the list below.")
            % {"n": len(result.conflicts)},
        )


@module_required("management")
def channels(request):
    form = FeedForm(request.POST or None, initial={"room": request.GET.get("room")})
    if request.method == "POST" and form.is_valid():
        feed = form.save()
        audit(request.user, "calendar.add", str(feed), feed)
        _sync_message(request, feed, ical.sync_feed(feed))
        return redirect("frontdesk:channels")
    rooms = Room.objects.filter(is_active=True).select_related("room_type").prefetch_related("feeds")
    base = request.build_absolute_uri("/")
    return render(
        request,
        "frontdesk/channels.html",
        {
            "form": form,
            "rows": [(room, ical.room_calendar_url(room, base), list(room.feeds.all())) for room in rooms],
            "feeds_with_conflicts": CalendarFeed.objects.exclude(conflicts=[]).select_related("room"),
            "needs_public": not HotelSettings.load().public_url,
            "tabs": [(reverse(n), label, n == "frontdesk:channels") for n, label in SETUP_TABS],
        },
    )


@require_POST
@module_required("management")
def channel_sync(request, pk=None):
    feeds = [get_object_or_404(CalendarFeed, pk=pk)] if pk else CalendarFeed.objects.filter(is_active=True)
    for feed in feeds:
        _sync_message(request, feed, ical.sync_feed(feed))
    return redirect("frontdesk:channels")


@require_POST
@module_required("management")
def channel_delete(request, pk):
    feed = get_object_or_404(CalendarFeed, pk=pk)
    audit(request.user, "calendar.remove", str(feed), feed)
    feed.delete()
    messages.success(request, _("Calendar removed. Bookings already copied stay in InnKeeper."))
    return redirect("frontdesk:channels")


def room_calendar(request, token):
    """Public, secret link: when this room is taken. No guest details."""
    room = ical.room_from_token(token)
    if room is None or not room.is_active:
        raise Http404
    response = HttpResponse(ical.export_room(room), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'inline; filename="room-{room.number}.ics"'
    response["Cache-Control"] = "no-store"
    return response
