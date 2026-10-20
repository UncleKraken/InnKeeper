"""Contacts: gathering them, consent, unsubscribing, and sending email campaigns to those who agreed."""

import logging
import threading
import time
from datetime import timedelta

from django.db import close_old_connections, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.core import email
from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings, audit

from .models import Campaign, CampaignRecipient, Contact

log = logging.getLogger(__name__)
_worker_lock = threading.Lock()
SEND_PAUSE = 1.0  # seconds between emails: kind to the mail server and its daily limits


def phone_key(phone: str) -> str:
    from apps.frontdesk.guest_messages import whatsapp_number

    return whatsapp_number(phone)


def find(email_: str = "", phone: str = "") -> Contact | None:
    if email_:
        c = Contact.objects.filter(email__iexact=email_.strip()).first()
        if c:
            return c
    key = phone_key(phone)
    if key:
        return Contact.objects.filter(phone_key=key).first()
    return None


def upsert(*, name: str, email_: str = "", phone: str = "", source: str, language: str = "", guest=None,
           consent: bool = False, consent_note: str = "", seen=None) -> Contact | None:
    """Add or update a contact. Consent is only ever added here (it is removed by unsubscribing)."""
    email_, phone, name = (email_ or "").strip(), (phone or "").strip(), (name or "").strip()
    if not (email_ or phone_key(phone)) or not name:
        return None
    c = find(email_, phone)
    if c is None:
        c = Contact(name=name[:160], email=email_, phone=phone, source=source, language=language or "sq", guest=guest)
    else:
        c.email = c.email or email_
        c.phone = c.phone or phone
        c.guest = c.guest or guest
        if language and c.source != Contact.Source.MANUAL:
            c.language = language
    if seen and (c.last_seen is None or seen > c.last_seen):
        c.last_seen = seen
    if consent and c.unsubscribed_at is None:
        c.marketing_ok, c.consent_at, c.consent_note = True, timezone.now(), consent_note[:200]
    elif consent:  # unsubscribed before and now agrees again (e.g. ticks the box on a new booking)
        c.marketing_ok, c.consent_at, c.consent_note, c.unsubscribed_at = True, timezone.now(), consent_note[:200], None
    c.save()
    return c


def sync_all() -> int:
    """Gather contacts from guests, loyalty cards, customer accounts and table bookings (no consent added)."""
    from apps.finance.models import CustomerAccount, LoyaltyCard
    from apps.frontdesk.guest_messages import language as guest_language
    from apps.frontdesk.models import Guest, Reservation
    from apps.outlets.models import TableBooking

    before = Contact.objects.count()
    last_stay = {}
    for r in Reservation.objects.exclude(status=Reservation.Status.CANCELLED).values("guest_id", "departure"):
        if r["departure"] and (r["guest_id"] not in last_stay or r["departure"] > last_stay[r["guest_id"]]):
            last_stay[r["guest_id"]] = r["departure"]
    for g in Guest.objects.all():
        lang = "sq" if guest_language(Reservation(guest=g)) == "sq" else "en"
        upsert(name=f"{g.first_name} {g.last_name}", email_=g.email, phone=g.phone, source=Contact.Source.GUEST,
               language=lang, guest=g, seen=last_stay.get(g.pk))
    for card in LoyaltyCard.objects.filter(is_active=True):
        upsert(name=card.name, phone=card.phone, source=Contact.Source.LOYALTY,
               seen=timezone.localtime(card.last_visit).date() if card.last_visit else None)
    for a in CustomerAccount.objects.filter(is_active=True):
        upsert(name=a.name, phone=a.phone, source=Contact.Source.ACCOUNT)
    for b in TableBooking.objects.exclude(phone="").order_by("date"):
        upsert(name=b.name, phone=b.phone, source=Contact.Source.TABLE, seen=b.date)
    return Contact.objects.count() - before


def unsubscribe(contact: Contact) -> None:
    if contact.unsubscribed_at is None:
        contact.unsubscribed_at = timezone.now()
        contact.marketing_ok = False
        contact.save(update_fields=["unsubscribed_at", "marketing_ok"])
        audit(None, "marketing.unsubscribe", contact.name, contact)


def audience(campaign: Campaign):
    qs = Contact.objects.filter(marketing_ok=True, unsubscribed_at__isnull=True).exclude(email="")
    if campaign.audience in ("sq", "en"):
        qs = qs.filter(language=campaign.audience)
    elif campaign.audience == Campaign.Audience.RECENT:
        qs = qs.filter(last_seen__gte=timezone.localdate() - timedelta(days=365))
    elif campaign.audience == Campaign.Audience.TAG:
        tag = campaign.tag.strip()
        qs = qs.filter(Q(tags__iexact=tag) | Q(tags__istartswith=f"{tag},") | Q(tags__icontains=f",{tag}") | Q(tags__icontains=f", {tag}"))
    return qs


def public_base() -> str:
    return HotelSettings.load().public_url.rstrip("/")


def start(campaign: Campaign, user) -> int:
    """Queue the campaign for everyone in its audience and start sending in the background."""
    hs = HotelSettings.load()
    if not hs.email_configured:
        raise BusinessError(_("Set up email first (Settings → Email)."))
    if not public_base():
        raise BusinessError(_("Set the public web address first (Settings → Online booking): the unsubscribe link must work from the guests' phones."))
    with transaction.atomic():
        campaign = Campaign.objects.select_for_update().get(pk=campaign.pk)
        if campaign.status != Campaign.Status.DRAFT:
            raise BusinessError(_("This campaign has already been sent."))
        people = list(audience(campaign))
        if not people:
            raise BusinessError(_("Nobody in this group has agreed to receive offers yet."))
        CampaignRecipient.objects.bulk_create([CampaignRecipient(campaign=campaign, contact=c) for c in people])
        campaign.status, campaign.sent_at = Campaign.Status.SENDING, timezone.now()
        campaign.save(update_fields=["status", "sent_at"])
    audit(user, "marketing.campaign", f"{campaign.subject} → {len(people)}", campaign)
    transaction.on_commit(kick)
    return len(people)


def send_one(r: CampaignRecipient, conn=None) -> bool:
    c, campaign = r.contact, r.campaign
    if not c.can_email:  # unsubscribed in the meantime
        CampaignRecipient.objects.filter(pk=r.pk).update(status=CampaignRecipient.Status.FAILED)
        return False
    unsub = public_base() + reverse("news:unsubscribe", args=[c.token])
    with translation.override(c.language):
        ok = email.send(
            c.email,
            campaign.subject,
            "marketing/email_campaign.html",
            {"campaign": campaign, "contact": c, "unsubscribe": unsub},
            language=c.language,
            headers={"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
            connection_=conn,
        )
    CampaignRecipient.objects.filter(pk=r.pk).update(
        status=CampaignRecipient.Status.SENT if ok else CampaignRecipient.Status.FAILED, sent_at=timezone.now()
    )
    return ok


def run_pending(limit: int = 200, pause: float = SEND_PAUSE) -> int:
    """Send what is waiting (called by the background worker and the background jobs)."""
    sent = 0
    pending = CampaignRecipient.objects.filter(status=CampaignRecipient.Status.PENDING).select_related("contact", "campaign")[:limit]
    for r in pending:
        try:
            sent += send_one(r)
        except Exception as e:  # one bad address must not stop the rest
            log.warning("Campaign email to %s failed: %s", r.contact_id, e)
            CampaignRecipient.objects.filter(pk=r.pk).update(status=CampaignRecipient.Status.FAILED)
        if pause:
            time.sleep(pause)
    for c in Campaign.objects.filter(status=Campaign.Status.SENDING):
        if not c.recipients.filter(status=CampaignRecipient.Status.PENDING).exists():
            Campaign.objects.filter(pk=c.pk).update(status=Campaign.Status.SENT)
    return sent


def kick() -> None:
    """Start a background sender unless one is already running."""
    if not _worker_lock.acquire(blocking=False):
        return

    def work():
        try:
            close_old_connections()
            while CampaignRecipient.objects.filter(status=CampaignRecipient.Status.PENDING).exists():
                if not run_pending(limit=50):
                    if not CampaignRecipient.objects.filter(status=CampaignRecipient.Status.PENDING).exists():
                        break
        except Exception as e:
            log.warning("Campaign sender stopped: %s", e)
        finally:
            close_old_connections()
            _worker_lock.release()

    threading.Thread(target=work, name="innkeeper-campaign", daemon=True).start()
