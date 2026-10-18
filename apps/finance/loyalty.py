"""
Gift vouchers and loyalty stamp cards.

Gift voucher: sold for cash or card (money received in advance, not revenue), spent at any till as a
payment method, in one or several visits, until its value is used up or it expires.

Loyalty card: a regular gives their phone number or card number at the till; every item marked
"earns a loyalty stamp" adds a stamp when the bill is paid. With enough stamps, one stamped item
on the bill is free (a discount on that bill), and the stamps start again.
"""

import secrets
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.businessday import business_date
from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings, audit

from .models import ZERO, GiftVoucher, LoyaltyCard, Payment

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def normalize(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def _new_voucher_code() -> str:
    while True:
        raw = "".join(secrets.choice(ALPHABET) for _i in range(8))
        code = f"{raw[:4]}-{raw[4:]}"
        if not GiftVoucher.objects.filter(code=code).exists():
            return code


def find_voucher(code: str, *, lock: bool = False) -> GiftVoucher:
    wanted = normalize(code)
    if not wanted:
        raise BusinessError(_("Type the voucher code."))
    qs = GiftVoucher.objects.select_for_update() if lock else GiftVoucher.objects.all()
    for v in qs.filter(code__startswith=wanted[:4]):
        if normalize(v.code) == wanted:
            return v
    raise BusinessError(_("No gift voucher with the code %(code)s.") % {"code": code.strip().upper()})


@transaction.atomic
def sell_voucher(*, amount: Decimal, method: str, user, buyer: str = "", note: str = "") -> GiftVoucher:
    hs = HotelSettings.load()
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount <= 0:
        raise BusinessError(_("Enter the value of the voucher."))
    if method not in (Payment.Method.CASH, Payment.Method.CARD, Payment.Method.BANK_TRANSFER):
        raise BusinessError(_("A voucher is paid in cash, by card or by bank transfer."))
    expires = business_date() + timedelta(days=round(hs.voucher_months * 30.44)) if hs.voucher_months else None
    voucher = GiftVoucher.objects.create(
        code=_new_voucher_code(), amount=amount, buyer=buyer[:120], note=note[:255], expires_on=expires, created_by=user
    )
    Payment.objects.create(voucher=voucher, method=method, amount=amount, reference=voucher.code, created_by=user)
    audit(user, "voucher.sold", f"{voucher.code} {amount} ({method})", voucher)
    return voucher


def check_spend(voucher: GiftVoucher, amount: Decimal) -> None:
    if voucher.voided:
        raise BusinessError(_("Gift voucher %(code)s was voided.") % {"code": voucher.code})
    if voucher.expired:
        raise BusinessError(
            _("Gift voucher %(code)s expired on %(date)s.") % {"code": voucher.code, "date": voucher.expires_on.strftime("%d.%m.%Y")}
        )
    balance = voucher.balance
    if balance <= 0:
        raise BusinessError(_("Gift voucher %(code)s is used up.") % {"code": voucher.code})
    if amount > balance:
        raise BusinessError(
            _("Gift voucher %(code)s has only %(left)s left.") % {"code": voucher.code, "left": f"{balance:.2f}"}
        )


@transaction.atomic
def void_voucher(voucher: GiftVoucher, *, user, reason: str) -> None:
    if not user.is_manager:
        raise BusinessError(_("Only a manager can void entries."))
    if not reason.strip():
        raise BusinessError(_("Give a reason for the void."))
    voucher = GiftVoucher.objects.select_for_update().get(pk=voucher.pk)
    if voucher.voided:
        return
    if voucher.used > 0:
        raise BusinessError(_("Part of this voucher was already spent, so it can't be voided."))
    now = timezone.now()
    for p in voucher.payments.filter(voided=False):
        p.voided, p.void_reason, p.voided_by, p.voided_at = True, reason[:255], user, now
        p.save(update_fields=["voided", "void_reason", "voided_by", "voided_at"])
    voucher.voided, voucher.void_reason = True, reason[:255]
    voucher.save(update_fields=["voided", "void_reason"])
    audit(user, "voucher.void", f"{voucher.code} – {reason}", voucher)


# ---------- Loyalty ----------


def _new_card_number() -> str:
    while True:
        number = "".join(secrets.choice("0123456789") for _i in range(6))
        if not LoyaltyCard.objects.filter(number=number).exists():
            return number


def find_card(text: str) -> LoyaltyCard | None:
    text = (text or "").strip()
    if not text:
        return None
    cards = LoyaltyCard.objects.filter(is_active=True)
    card = cards.filter(number=text).first()
    if card:
        return card
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 6:
        for c in cards.exclude(phone=""):
            if "".join(ch for ch in c.phone if ch.isdigit()).endswith(digits[-8:]):
                return c
    return None


def create_card(*, name: str, phone: str = "") -> LoyaltyCard:
    if not name.strip():
        raise BusinessError(_("Type the customer's name."))
    return LoyaltyCard.objects.create(number=_new_card_number(), name=name.strip()[:120], phone=phone.strip()[:40])


def stamped_units(order) -> int:
    return sum(line.quantity for line in order.active_lines if line.item_id and line.item and line.item.earns_stamp)


def reward_ready(card: LoyaltyCard | None) -> bool:
    return bool(card and card.stamps >= HotelSettings.load().loyalty_stamps)


@transaction.atomic
def attach_card(order, card: LoyaltyCard, user) -> None:
    from apps.outlets.models import Order

    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != Order.Status.OPEN:
        raise BusinessError(_("This order is already closed."))
    order.loyalty_card = card
    order.save(update_fields=["loyalty_card"])
    audit(user, "loyalty.attach", f"#{order.number} → {card}", order)


@transaction.atomic
def give_reward(order, user) -> Decimal:
    """One stamped item on this bill is free: the cheapest one, as a discount."""
    from apps.outlets.models import Order

    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != Order.Status.OPEN or not order.loyalty_card_id:
        raise BusinessError(_("Add the customer's loyalty card first."))
    if order.loyalty_reward:
        raise BusinessError(_("This bill already has its free item."))
    card = LoyaltyCard.objects.select_for_update().get(pk=order.loyalty_card_id)
    needed = HotelSettings.load().loyalty_stamps
    if card.stamps < needed:
        raise BusinessError(_("%(name)s has %(n)s of %(need)s stamps.") % {"name": card.name, "n": card.stamps, "need": needed})
    prices = [line.unit_price for line in order.active_lines if line.item_id and line.item and line.item.earns_stamp]
    if not prices:
        raise BusinessError(_("Add an item that earns stamps to the bill first."))
    free = min(prices)
    if order.payments.filter(voided=False).exists():
        raise BusinessError(_("Give the free item before taking a payment."))
    order.discount = min(order.subtotal, order.discount + free)
    reason = _("Loyalty card: free item")
    order.discount_reason = (f"{order.discount_reason} + {reason}" if order.discount_reason else reason)[:120]
    order.loyalty_reward = True
    order.save(update_fields=["discount", "discount_reason", "loyalty_reward"])
    card.stamps -= needed
    card.rewards += 1
    card.save(update_fields=["stamps", "rewards"])
    audit(user, "loyalty.reward", f"#{order.number} {card} −{free}", order)
    return free


def on_order_closed(order) -> None:
    """Called when a bill is paid: add its stamps (the free item doesn't earn one)."""
    if not order.loyalty_card_id or order.loyalty_stamps:
        return
    n = stamped_units(order) - (1 if order.loyalty_reward else 0)
    if n <= 0:
        return
    LoyaltyCard.objects.filter(pk=order.loyalty_card_id).update(
        stamps=F("stamps") + n, last_visit=timezone.now()
    )
    type(order).objects.filter(pk=order.pk).update(loyalty_stamps=n)
    order.loyalty_stamps = n


def on_order_voided(order) -> None:
    """A voided bill takes back the stamps it gave (never below zero)."""
    if not order.loyalty_card_id or not order.loyalty_stamps:
        return
    card = LoyaltyCard.objects.select_for_update().get(pk=order.loyalty_card_id)
    card.stamps = max(0, card.stamps - order.loyalty_stamps)
    card.save(update_fields=["stamps"])
    type(order).objects.filter(pk=order.pk).update(loyalty_stamps=0)


def voucher_totals(day) -> dict:
    """For the day close: vouchers sold (money in advance) and vouchers spent (not money)."""
    from .models import net

    amount = net("amount", day)
    sold = Payment.objects.period(day).filter(voucher__isnull=False).exclude(method=Payment.Method.VOUCHER)
    spent = Payment.objects.period(day).filter(method=Payment.Method.VOUCHER)
    return {
        "vouchers_sold": sold.aggregate(t=amount)["t"] or ZERO,
        "vouchers_spent": spent.aggregate(t=amount)["t"] or ZERO,
    }
