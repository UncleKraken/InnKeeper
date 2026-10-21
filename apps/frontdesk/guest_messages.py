"""
Messages to guests: arrival information a few days before the stay, and a thank-you with the review link
the day after they leave.

By email, sent by the background jobs at the hour chosen in Settings (each one once only), or by the
receptionist from the reservation page. For guests without email, the reservation page also offers a
WhatsApp button that opens the chat with the message ready to send (free, no account or API needed).
"""

import logging
import re
from datetime import datetime, time, timedelta
from urllib.parse import quote

from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.core import email
from apps.core.models import HotelSettings, audit

from .models import Reservation

log = logging.getLogger(__name__)

PRE_ARRIVAL = "pre_arrival"
REVIEW = "review"
FIELDS = {PRE_ARRIVAL: "pre_arrival_sent_at", REVIEW: "review_sent_at"}
MAX_PER_RUN = 60


def language(res: Reservation, hs=None) -> str:
    """The guest's language: what they booked in, else Albanian for Albanians and English for everyone else."""
    if res.guest_language:
        return res.guest_language
    nat = (res.guest.nationality or "").strip().lower()
    if nat in ("albania", "shqipëri", "shqiperi", "shqipëria", "al", "alb", "kosovo", "kosova"):
        return "sq"
    if nat:
        return "en"
    return (hs or HotelSettings.load()).default_language or "sq"


def map_link(hs) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={quote(hs.address)}" if hs.address else ""


def subject(kind: str, res: Reservation, hs) -> str:
    if kind == PRE_ARRIVAL:
        return _("Your stay at %(hotel)s on %(date)s") % {"hotel": hs.name, "date": res.arrival.strftime("%d.%m")}
    return _("Thank you for staying at %(hotel)s") % {"hotel": hs.name}


def text(kind: str, res: Reservation, hs) -> str:
    """The plain message (for WhatsApp, and the start of the email)."""
    name = res.guest.first_name or str(res.guest)
    if kind == PRE_ARRIVAL:
        parts = [
            _("Dear %(name)s,") % {"name": name},
            _("We look forward to welcoming you on %(date)s. Check-in is from %(time)s.")
            % {"date": res.arrival.strftime("%d.%m.%Y"), "time": hs.check_in_time.strftime("%H:%M")},
        ]
        from . import checkin

        if checkin.offered(res) and not res.online_checkin_at:
            parts.append(_("Save time at reception: check in online before you arrive.") + "\n" + checkin.link(res))
        if hs.message_pre_arrival_text.strip():
            parts.append(hs.message_pre_arrival_text.strip())
        if hs.address:
            parts.append(_("Address: %(a)s") % {"a": hs.address} + "\n" + map_link(hs))
        if hs.phone:
            parts.append(_("If you need anything, call or message us: %(p)s") % {"p": hs.phone})
    else:
        parts = [
            _("Dear %(name)s,") % {"name": name},
            hs.message_review_text.strip() or _("Thank you for staying with us. We hope you enjoyed it and would be glad to welcome you again."),
        ]
        if hs.message_review_url:
            parts.append(_("If you have a minute, a short review helps us a lot:") + "\n" + hs.message_review_url)
    parts.append(hs.name)
    return "\n\n".join(parts)


def send(kind: str, res: Reservation, user=None, *, force: bool = False) -> bool:
    """Email one message to the guest. Each kind goes once only (unless resent by hand with force)."""
    hs = HotelSettings.load()
    if not res.guest.email or not hs.email_configured:
        return False
    field = FIELDS[kind]
    now = timezone.now()
    qs = Reservation.objects.filter(pk=res.pk)
    if not force:
        qs = qs.filter(**{f"{field}__isnull": True})
    if not qs.update(**{field: now}):  # claimed first, so two background runs never send it twice
        return False
    lang = language(res, hs)
    with translation.override(lang):
        ok = email.send(
            res.guest.email,
            subject(kind, res, hs),
            "booking/email_message.html",
            {"r": res, "kind": kind, "body": text(kind, res, hs), "map": map_link(hs), "review_url": hs.message_review_url,
             "checkin_url": _checkin_url(kind, res)},
            language=lang,
        )
    if not ok:
        Reservation.objects.filter(pk=res.pk).update(**{field: getattr(res, field)})  # try again next time
        return False
    setattr(res, field, now)
    audit(user, f"guest_message.{kind}", f"{res.code} {res.guest} → {res.guest.email}", res)
    return True


def _checkin_url(kind: str, res: Reservation) -> str:
    from . import checkin

    return checkin.link(res) if kind == PRE_ARRIVAL and checkin.offered(res) and not res.online_checkin_at else ""


def due(kind: str, today=None):
    hs = HotelSettings.load()
    today = today or timezone.localdate()
    base = Reservation.objects.select_related("guest", "room").exclude(guest__email="")
    if kind == PRE_ARRIVAL:
        return base.filter(
            status=Reservation.Status.BOOKED,
            confirmed=True,
            arrival__gt=today,
            arrival__lte=today + timedelta(days=hs.message_pre_arrival_days),
            pre_arrival_sent_at__isnull=True,
            created_at__lt=timezone.now() - timedelta(hours=1),  # they've just had the confirmation
        )
    since = timezone.make_aware(datetime.combine(today - timedelta(days=3), time.min))
    until = timezone.make_aware(datetime.combine(today, time.min))
    return base.filter(
        status=Reservation.Status.CHECKED_OUT,
        checked_out_at__gte=since,
        checked_out_at__lt=until,  # from the day after they leave, for a few days if the PC was off
        review_sent_at__isnull=True,
    )


def run(now=None) -> int:
    """Called every few minutes by the background jobs: sends what is due, at the chosen hour."""
    hs = HotelSettings.load()
    if not hs.email_configured or not (hs.message_pre_arrival or hs.message_review):
        return 0
    now = now or timezone.now()
    if timezone.localtime(now).hour < hs.message_hour:
        return 0
    today = timezone.localdate(now)
    sent = 0
    for kind, on in ((PRE_ARRIVAL, hs.message_pre_arrival), (REVIEW, hs.message_review and hs.message_review_url)):
        if not on:
            continue
        for res in due(kind, today)[:MAX_PER_RUN]:
            try:
                sent += send(kind, res)
            except Exception as e:  # never stop the other background jobs
                log.warning("Guest message %s for %s failed: %s", kind, res.pk, e)
    return sent


def whatsapp_number(phone: str) -> str:
    """International digits for wa.me: +355 69…, 00355 69… and 069… (Albanian mobile) all become 35569…"""
    digits = re.sub(r"\D", "", phone or "")
    if (phone or "").strip().startswith("00"):
        digits = digits[2:]
    elif digits.startswith("06") and len(digits) == 10:
        digits = "355" + digits[1:]
    return digits if len(digits) >= 8 else ""


def whatsapp_link(kind: str, res: Reservation) -> str:
    number = whatsapp_number(res.guest.phone)
    if not number:
        return ""
    hs = HotelSettings.load()
    with translation.override(language(res, hs)):
        return f"https://wa.me/{number}?text={quote(text(kind, res, hs))}"
