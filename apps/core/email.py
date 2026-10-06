"""Sending email with the SMTP account set in Settings → Email. Quietly does nothing if no account is set."""

import logging

from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.html import strip_tags

from .models import HotelSettings

log = logging.getLogger(__name__)


def connection(hs: HotelSettings | None = None):
    hs = hs or HotelSettings.load()
    from django.conf import settings

    if getattr(settings, "EMAIL_BACKEND", "").endswith("locmem.EmailBackend"):
        return get_connection()  # tests
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=hs.smtp_host,
        port=hs.smtp_port,
        username=hs.smtp_username or None,
        password=hs.smtp_password or None,
        use_tls=hs.smtp_security == "tls",
        use_ssl=hs.smtp_security == "ssl",
        timeout=15,
    )


def send(to: str | list[str], subject: str, template: str, context: dict, *, language: str = "", reply_to=None) -> bool:
    """Render `template` (HTML) and send it. Returns False if email isn't set up or sending failed."""
    hs = HotelSettings.load()
    recipients = [to] if isinstance(to, str) else [r for r in to if r]
    if not hs.email_configured or not recipients:
        return False
    with translation.override(language or hs.default_language):
        html = render_to_string(template, {"hotel": hs, **context})
        subject = str(subject)
    msg = EmailMultiAlternatives(
        subject=subject,
        body=strip_tags(html),
        from_email=f"{hs.name} <{hs.email_from or hs.smtp_username}>",
        to=recipients,
        reply_to=reply_to or ([hs.email] if hs.email else None),
        connection=connection(hs),
    )
    msg.attach_alternative(html, "text/html")
    try:
        msg.send()
    except Exception as e:  # network/SMTP errors must never break a booking
        log.warning("Email to %s failed: %s", recipients, e)
        return False
    return True
