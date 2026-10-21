"""Customer accounts (tabs) and staff shifts: the rules. Views are in tab_views.py."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings, audit

from .models import ZERO, Charge, CustomerAccount, Payment, Shift


# ---------- Customer accounts ----------


@transaction.atomic
def pay_account(account: CustomerAccount, *, amount: Decimal, method: str, user, reference: str = "") -> Payment:
    """The customer pays (part of) what they owe. A minus amount gives money back (managers only)."""
    account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount == 0:
        raise BusinessError(_("Enter an amount."))
    if amount < 0 and not getattr(user, "is_manager", False):
        raise BusinessError(_("Only a manager can give money back."))
    payment = Payment.objects.create(
        account=account, amount=amount, method=method, reference=reference[:80], created_by=user
    )
    audit(user, "account.payment", f"{account.name}: {payment.get_method_display()} {amount}", account)
    return payment


def statement(account: CustomerAccount) -> list[dict]:
    """Everything on the account, oldest first, with the running balance."""
    rows = []
    for c in account.charges.select_related("order", "order__outlet").all():
        rows.append({"when": c.created_at, "date": c.business_date, "text": c.description, "charge": c.amount,
                     "payment": None, "voided": c.voided, "order": c.order, "entry": c})
    for p in account.payments.all():
        rows.append({"when": p.created_at, "date": p.business_date, "text": p.get_method_display(),
                     "charge": None, "payment": p.amount, "voided": p.voided, "order": None, "entry": p})
    rows.sort(key=lambda r: r["when"])
    balance = account.opening_balance
    for r in rows:
        if not r["voided"]:
            balance += (r["charge"] or ZERO) - (r["payment"] or ZERO)
        r["balance"] = balance
    return rows


def accounts_with_balances(qs=None) -> list[CustomerAccount]:
    accounts = list((qs if qs is not None else CustomerAccount.objects.all()))
    owed = {
        r["account"]: r["t"]
        for r in Charge.objects.filter(account__in=accounts, voided=False).values("account").annotate(t=Sum("amount"))
    }
    paid = {
        r["account"]: r["t"]
        for r in Payment.objects.filter(account__in=accounts, voided=False).values("account").annotate(t=Sum("amount"))
    }
    for a in accounts:
        a.current_balance = a.opening_balance + (owed.get(a.pk) or ZERO) - (paid.get(a.pk) or ZERO)
    return accounts


# ---------- Shifts ----------


def open_shift_for(user) -> Shift | None:
    if not getattr(user, "is_authenticated", False):
        return None
    return Shift.objects.filter(user=user, closed_at__isnull=True).first()


@transaction.atomic
def start_shift(user, opening_float: Decimal = ZERO) -> Shift:
    if open_shift_for(user):
        raise BusinessError(_("You already have a shift open."))
    opening_float = Decimal(opening_float or 0).quantize(Decimal("0.01"))
    if opening_float < 0:
        raise BusinessError(_("Enter an amount of zero or more."))
    shift = Shift.objects.create(user=user, opening_float=opening_float)
    audit(user, "shift.start", f"{opening_float}", shift)
    return shift


def summary(shift: Shift) -> dict:
    """What happened in the shift and how much cash should be handed in.

    Expected cash = cash at the start + cash taken − card tips paid out to the staff member
    (the guest's card paid the tip, the waiter gets it in cash from the drawer)."""
    payments = shift.payments.filter(voided=False)
    by_method: dict[str, Decimal] = {}
    for row in payments.values("method").annotate(t=Sum("amount"), tips=Sum("tip")):
        by_method[row["method"]] = row["t"] or ZERO
    cash = by_method.get(Payment.Method.CASH, ZERO)
    tips_cash = payments.filter(method=Payment.Method.CASH).aggregate(t=Sum("tip"))["t"] or ZERO
    tips_other = payments.exclude(method=Payment.Method.CASH).aggregate(t=Sum("tip"))["t"] or ZERO
    labels = dict(Payment.Method.choices)
    from . import currency

    foreign = currency.drawer(payments)
    code = shift.second_currency or payments.exclude(foreign_currency="").values_list("foreign_currency", flat=True).first() or ""
    hs = HotelSettings.load()
    return {
        "methods": [(labels.get(m, m), v) for m, v in by_method.items() if v],
        "total": sum(by_method.values(), ZERO),
        "count": payments.count(),
        "cash": cash,
        "tips_cash": tips_cash,
        "tips_card": tips_other,
        "foreign_code": code,
        "foreign_symbol": hs.second_currency_symbol if code and code == hs.second_currency else code,
        "foreign_received": foreign["received"],
        "foreign_value": foreign["value"],
        "expected_cash": shift.opening_float + cash - tips_other - foreign["value"],
    }


@transaction.atomic
def end_shift(shift: Shift, *, counted: Decimal, user, notes: str = "", counted_second: Decimal | None = None) -> Shift:
    shift = Shift.objects.select_for_update().get(pk=shift.pk)
    if not shift.is_open:
        raise BusinessError(_("This shift is already closed."))
    if shift.user_id != user.pk and not getattr(user, "is_manager", False):
        raise BusinessError(_("Only the staff member or a manager can close this shift."))
    counted = Decimal(counted).quantize(Decimal("0.01"))
    if counted < 0:
        raise BusinessError(_("Enter an amount of zero or more."))
    s = summary(shift)
    shift.expected_cash = s["expected_cash"]
    shift.counted_cash = counted
    if s["foreign_code"]:
        shift.second_currency = s["foreign_code"]
        shift.expected_second = s["foreign_received"]
        shift.counted_second = Decimal(counted_second).quantize(Decimal("0.01")) if counted_second is not None else None
    shift.closed_at = timezone.now()
    shift.notes = notes.strip()[:255]
    shift.save(update_fields=["expected_cash", "counted_cash", "second_currency", "expected_second", "counted_second", "closed_at", "notes"])
    audit(user, "shift.end", f"{shift.user} expected {shift.expected_cash} counted {counted}", shift)
    return shift
