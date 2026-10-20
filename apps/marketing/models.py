"""
Contacts and marketing.

A contact is a person the business can reach: from hotel guests, loyalty cards, customer accounts and
table bookings, or added by hand. Marketing messages go only to contacts who agreed to receive them
(Albania's personal data law, like the GDPR, asks for that consent), and every message has a one-click
unsubscribe. When and how each person agreed is kept, as the law expects.
"""

import secrets

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


def new_token() -> str:
    return secrets.token_urlsafe(18)


class Contact(models.Model):
    class Source(models.TextChoices):
        GUEST = "guest", _("Hotel guest")
        BOOKING = "booking", _("Online booking")
        SIGNUP = "signup", _("Sign-up page")
        LOYALTY = "loyalty", _("Loyalty card")
        ACCOUNT = "account", _("Customer account")
        TABLE = "table", _("Table booking")
        MANUAL = "manual", _("Added by hand")

    name = models.CharField(_("name"), max_length=160)
    email = models.EmailField(_("email"), blank=True, db_index=True)
    phone = models.CharField(_("phone"), max_length=40, blank=True, db_index=True)
    phone_key = models.CharField(max_length=20, blank=True, db_index=True, editable=False)  # +355 69…, 069… → 35569…
    language = models.CharField(_("language"), max_length=5, choices=[("sq", "Shqip"), ("en", "English")], default="sq")
    source = models.CharField(_("from"), max_length=10, choices=Source.choices, default=Source.MANUAL)
    marketing_ok = models.BooleanField(_("agreed to receive offers"), default=False)
    consent_at = models.DateTimeField(null=True, blank=True, editable=False)
    consent_note = models.CharField(_("how they agreed"), max_length=200, blank=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True, editable=False)
    tags = models.CharField(_("tags"), max_length=200, blank=True, help_text=_("Words to group contacts, e.g. wedding, company, VIP."))
    notes = models.TextField(_("notes"), blank=True)
    guest = models.ForeignKey("frontdesk.Guest", null=True, blank=True, on_delete=models.SET_NULL, related_name="contacts")
    last_seen = models.DateField(_("last visit"), null=True, blank=True)
    token = models.CharField(max_length=40, unique=True, default=new_token, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("contact")
        verbose_name_plural = _("contacts")

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        from apps.frontdesk.guest_messages import whatsapp_number

        self.phone_key = whatsapp_number(self.phone)
        if kwargs.get("update_fields") is not None and "phone" in kwargs["update_fields"]:
            kwargs["update_fields"] = list(kwargs["update_fields"]) + ["phone_key"]
        super().save(*args, **kwargs)

    @property
    def can_email(self) -> bool:
        return bool(self.email) and self.marketing_ok and self.unsubscribed_at is None

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


class Campaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SENDING = "sending", _("Sending")
        SENT = "sent", _("Sent")

    class Audience(models.TextChoices):
        ALL = "all", _("Everyone who agreed")
        SQ = "sq", _("Albanian speakers")
        EN = "en", _("English speakers")
        RECENT = "recent", _("Visited in the last 12 months")
        TAG = "tag", _("With a tag")

    subject = models.CharField(_("subject"), max_length=150)
    body = models.TextField(_("message"), help_text=_("Plain text. Links are made clickable. “Dear …,” and the unsubscribe link are added."))
    audience = models.CharField(_("send to"), max_length=10, choices=Audience.choices, default=Audience.ALL)
    tag = models.CharField(_("tag"), max_length=60, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.subject


class CampaignRecipient(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting")
        SENT = "sent", _("Sent")
        FAILED = "failed", _("Failed")

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="recipients")
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="received")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campaign", "contact"], name="one_send_per_contact")]
