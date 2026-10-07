"""Rooms & rates → Channel manager: connect to Channex, link room types, see what arrived."""

import threading

from django import forms
from django.contrib import messages
from django.core import signing
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.forms import StyledFormMixin
from apps.core.models import HotelSettings, audit

from . import channex
from .models import ChannelBooking, ChannelSyncState, RoomType
from .views import SETUP_TABS

WEBHOOK_SALT = "innkeeper.channex-webhook"


class ChannexSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = ["channex_enabled", "channex_staging", "channex_property_id", "channex_api_key", "channex_days_ahead"]
        widgets = {"channex_api_key": forms.PasswordInput(render_value=True)}

    def clean_channex_days_ahead(self):
        v = self.cleaned_data["channex_days_ahead"]
        if not 30 <= v <= 730:
            raise forms.ValidationError(_("Choose between 30 and 730 days."))
        return v

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("channex_enabled"):
            for f in ("channex_api_key", "channex_property_id"):
                if not cleaned.get(f):
                    self.add_error(f, _("Needed to connect."))
        return cleaned


def webhook_token() -> str:
    return signing.Signer(salt=WEBHOOK_SALT).sign(HotelSettings.load().channex_property_id or "-").split(":")[-1]


def _tabs():
    return [(reverse(n), label, n == "frontdesk:channel_manager") for n, label in SETUP_TABS]


@module_required("management")
def channel_manager(request):
    hs = HotelSettings.load()
    form = (
        ChannexSettingsForm(request.POST or None, instance=hs)
        if request.POST.get("form") == "settings"
        else ChannexSettingsForm(instance=hs)
    )
    if request.method == "POST" and request.POST.get("form") == "settings" and form.is_valid():
        form.save()
        audit(request.user, "settings.channel_manager", hs.name, hs)
        messages.success(request, _("Settings saved."))
        return redirect("frontdesk:channel_manager")
    if request.method == "POST" and request.POST.get("form") == "mapping":
        for rt in RoomType.objects.all():
            rt.channex_room_type_id = request.POST.get(f"rt{rt.pk}", "").strip()[:64]
            rt.channex_rate_plan_id = request.POST.get(f"rp{rt.pk}", "").strip()[:64]
            rt.save(update_fields=["channex_room_type_id", "channex_rate_plan_id"])
        audit(request.user, "channel.mapping", "room types linked")
        messages.success(request, _("Room types linked. Availability and prices will be sent now."))
        return redirect("frontdesk:channel_manager")

    remote_types, remote_plans, remote_error = [], [], ""
    if hs.channex_api_key and hs.channex_property_id:
        try:
            client = channex.Client.from_settings(hs)
            remote_types = client.room_types(hs.channex_property_id)
            remote_plans = client.rate_plans(hs.channex_property_id)
        except channex.ChannexError as e:
            remote_error = str(e)
    base = (hs.public_url or request.build_absolute_uri("/")).rstrip("/")
    return render(
        request,
        "frontdesk/channel_manager.html",
        {
            "form": form,
            "tabs": _tabs(),
            "room_types": RoomType.objects.filter(is_active=True),
            "remote_types": remote_types,
            "remote_plans": remote_plans,
            "remote_error": remote_error,
            "state": ChannelSyncState.get(),
            "bookings": ChannelBooking.objects.all()[:30],
            "webhook_url": f"{base}{reverse('channex_webhook', args=[webhook_token()])}",
        },
    )


@require_POST
@module_required("management")
def channel_manager_sync(request):
    what = request.POST.get("what")
    try:
        if what == "push":
            channex.push(force=True)
            messages.success(request, _("Availability and prices sent to the channel manager."))
        else:
            n = len(channex.pull())
            messages.success(request, _("%(n)s booking update(s) received.") % {"n": n})
    except channex.ChannexError as e:
        messages.error(request, _("The channel manager could not be reached: %(e)s") % {"e": e})
    return redirect("frontdesk:channel_manager")


@csrf_exempt
@require_POST
def channex_webhook(request, token):
    """Channex calls this when something happens; we then read the booking feed (the body isn't trusted)."""
    hs = HotelSettings.load()
    if not hs.channex_configured or token != webhook_token():
        raise Http404

    def run():
        from django.db import connection

        try:
            channex.pull()
            channex.push()
        except Exception:  # the regular loop will retry
            pass
        finally:
            connection.close()

    threading.Thread(target=run, daemon=True).start()
    return HttpResponse("OK")
