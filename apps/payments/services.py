"""Payment links: create them, send them, and record the money when the provider confirms it."""

import logging
from decimal import Decimal

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import email
from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings, audit
from apps.finance.models import Payment

from .models import PaymentLink
from .providers import ProviderError, Result, get_provider

log = logging.getLogger(__name__)


def public_url(path: str, base_url: str = "") -> str:
    base = (HotelSettings.load().public_url or base_url).rstrip("/")
    return f"{base}{path}"


def link_url(link: PaymentLink, base_url: str = "") -> str:
    return public_url(reverse("payments:pay", args=[link.token]), base_url)


def create_link(
    *, reservation=None, amount: Decimal, purpose: str, user=None, description: str = "", email_to: str = ""
) -> PaymentLink:
    hs = HotelSettings.load()
    if not hs.payments_configured:
        raise BusinessError(_("Set up a payment provider in Settings → Payments first."))
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount <= 0:
        raise BusinessError(_("Enter an amount above zero."))
    if not description:
        label = dict(PaymentLink.Purpose.choices)[purpose]
        description = f"{hs.name} – {label}" + (f" {reservation.code}" if reservation else "")
    link = PaymentLink.objects.create(
        reservation=reservation,
        purpose=purpose,
        description=description[:200],
        amount=amount,
        currency=hs.currency,
        provider=hs.payment_provider,
        test_mode=hs.payment_test_mode,
        email=email_to or (reservation.guest.email if reservation else ""),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    audit(user, "payment_link.create", f"{link.description} {amount}", link)
    return link


def start_checkout(link: PaymentLink, base_url: str = "", lang: str = "en") -> str:
    """Create the payment at the provider and return the page to send the guest to."""
    if not link.is_open:
        raise BusinessError(_("This payment link is no longer open."))
    provider = get_provider(HotelSettings.load())
    if provider is None or provider.name != link.provider:
        raise BusinessError(_("Card payments are not available at the moment."))
    done = public_url(reverse("payments:done", args=[link.token]), base_url)
    try:
        if provider.name == "pok":
            checkout = provider.create(
                link,
                return_url=done,
                webhook_url=public_url(reverse("payments:pok_webhook", args=[link.token]), base_url),
            )
        else:
            checkout = provider.create(
                link,
                return_url=done,
                cancel_url=public_url(reverse("payments:pay", args=[link.token]), base_url) + "?cancelled=1",
                callback_url=public_url(reverse("payments:paysera_callback"), base_url),
                lang="ENG",
            )
    except ProviderError as e:
        link.error = str(e)[:255]
        link.save(update_fields=["error"])
        log.warning("Payment checkout failed for %s: %s", link.token, e)
        raise BusinessError(_("The payment page could not be opened. Please try again in a moment.")) from e
    link.external_id, link.checkout_url, link.error = checkout.external_id, checkout.url, ""
    link.save(update_fields=["external_id", "checkout_url", "error"])
    return checkout.url


@transaction.atomic
def record_result(link: PaymentLink, result: Result, *, source: str) -> PaymentLink:
    link = PaymentLink.objects.select_for_update().get(pk=link.pk)
    if link.status == PaymentLink.Status.PAID:
        return link
    if not result.paid:
        if result.uncertain:
            link.error = _(
                "The provider didn't confirm the payment yet. Check its merchant app before marking it paid."
            )
            link.save(update_fields=["error"])
        return link
    if result.amount_minor is not None and result.amount_minor != link.minor_units:
        link.error = _("Amount mismatch: expected %(a)s, provider reported %(b)s.") % {
            "a": link.minor_units,
            "b": result.amount_minor,
        }
        link.save(update_fields=["error"])
        audit(None, "payment_link.mismatch", f"{link.token}: {link.error}", link)
        return link
    if result.currency and result.currency.upper() != link.currency.upper():
        link.error = _("Currency mismatch: %(c)s.") % {"c": result.currency}
        link.save(update_fields=["error"])
        return link
    _mark_paid(link, reference=f"{link.provider.upper()} {result.external_id or link.external_id}"[:80], user=None)
    audit(None, "payment_link.paid", f"{link.description} {link.amount} ({source})", link)
    _notify_staff(link)
    return link


def mark_paid_by_hand(link: PaymentLink, user) -> PaymentLink:
    if not user.is_manager:
        raise BusinessError(_("Only a manager can mark an online payment as received."))
    with transaction.atomic():
        link = PaymentLink.objects.select_for_update().get(pk=link.pk)
        if link.status != PaymentLink.Status.PENDING:
            raise BusinessError(_("This payment link is no longer open."))
        _mark_paid(link, reference=f"{link.provider.upper()} {link.external_id}"[:80], user=user)
    audit(user, "payment_link.paid_by_hand", f"{link.description} {link.amount}", link)
    return link


def cancel_link(link: PaymentLink, user) -> PaymentLink:
    if link.status != PaymentLink.Status.PENDING:
        raise BusinessError(_("This payment link is no longer open."))
    link.status = PaymentLink.Status.CANCELLED
    link.save(update_fields=["status"])
    audit(user, "payment_link.cancel", f"{link.description} {link.amount}", link)
    return link


def _mark_paid(link: PaymentLink, *, reference: str, user) -> None:
    from apps.frontdesk import services as fd

    payment = None
    if link.reservation_id:
        folio = link.reservation.folio
        if folio.status == folio.Status.OPEN:
            payment = fd.add_payment(
                folio, amount=link.amount, method=Payment.Method.ONLINE, reference=reference, user=user
            )
    if payment is None:
        payment = Payment.objects.create(
            amount=link.amount, method=Payment.Method.ONLINE, reference=reference, created_by=user
        )
    link.status = PaymentLink.Status.PAID
    link.paid_at = timezone.now()
    link.payment = payment
    link.error = ""
    link.save(update_fields=["status", "paid_at", "payment", "error"])


def _notify_staff(link: PaymentLink) -> None:
    hs = HotelSettings.load()
    if hs.notify_email:
        email.send(
            hs.notify_email,
            _("Card payment received: %(amount)s %(cur)s – %(desc)s")
            % {"amount": link.amount, "cur": link.currency, "desc": link.description},
            "payments/email_staff.html",
            {"link": link},
        )


def send_link_email(link: PaymentLink, base_url: str = "") -> bool:
    if not link.email:
        return False
    lang = (link.reservation.guest_language if link.reservation else "") or HotelSettings.load().default_language
    from django.utils import translation

    with translation.override(lang):
        subject = _("Payment request: %(desc)s") % {"desc": link.description}
    return email.send(
        link.email, subject, "payments/email_guest.html", {"link": link, "url": link_url(link, base_url)}, language=lang
    )
