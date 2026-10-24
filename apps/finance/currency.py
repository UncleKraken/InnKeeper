"""
Cash in a second currency: a guest pays a lek bill with euros (or a euro bill with lekë).

The bill and every report stay in the main currency. The payment keeps what was handed over in the second
currency and at which rate; its value in the main currency is the `tendered` amount, so the change (given in
the main currency) works as for any cash payment. The cash drawer is counted in both currencies.
"""

from decimal import ROUND_HALF_UP, ROUND_UP, Decimal

from django.utils.translation import gettext as _

from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def settings_or_none():
    hs = HotelSettings.load()
    return hs if hs.second_cash else None


def to_main(foreign: Decimal, rate: Decimal) -> Decimal:
    return (Decimal(foreign) * Decimal(rate)).quantize(CENT, rounding=ROUND_HALF_UP)


# Currencies paid in whole units in practice (no coins under 1): the amount due is rounded up to a whole one.
WHOLE_UNITS = {"ALL", "JPY", "KRW", "HUF", "ISK"}


def whole_units(currency: str) -> bool:
    return (currency or "").upper() in WHOLE_UNITS


def due_in_second(amount: Decimal, rate: Decimal, currency: str = "") -> Decimal:
    """What the guest must hand over in the second currency to cover `amount` (rounded up to the cent, or to
    a whole unit for currencies such as the lek)."""
    step = Decimal("1") if whole_units(currency) else CENT
    return (Decimal(amount) / Decimal(rate)).quantize(step, rounding=ROUND_UP).quantize(CENT)


def foreign_payment(currency: str, amount) -> dict | None:
    """The fields for a cash payment handed over in the second currency, or None for the main currency.

    Returns {"tendered": value in the main currency, "foreign_currency", "foreign_amount", "foreign_rate"}."""
    if not currency:
        return None
    hs = settings_or_none()
    if hs is None or currency.upper() != hs.second_currency.upper():
        raise BusinessError(_("This currency is not set up (Settings → Business details)."))
    if amount is None:
        raise BusinessError(_("Enter how much was handed over in %(c)s.") % {"c": hs.second_currency})
    amount = Decimal(amount).quantize(CENT)
    if amount <= 0:
        raise BusinessError(_("Enter an amount above zero."))
    rate = hs.second_currency_rate
    return {
        "tendered": to_main(amount, rate),
        "foreign_currency": hs.second_currency.upper(),
        "foreign_amount": amount,
        "foreign_rate": rate,
    }


def drawer(payments) -> dict:
    """Second-currency cash in a set of live payments: how much came in, and its value in the main currency
    (which did not go into the main-currency drawer: change was given from it instead)."""
    foreign = payments.filter(method="cash").exclude(foreign_currency="")
    received = ZERO
    value = ZERO
    for p in foreign.only("foreign_amount", "tendered"):
        received += p.foreign_amount or ZERO
        value += p.tendered or ZERO
    return {"received": received, "value": value}


def drop_odd_change(foreign: dict, amount) -> dict:
    """In a whole-unit currency the guest hands over the amount rounded up to a whole lek: the few cents over
    are not change to give back (there is no coin for them), so the payment counts as exact."""
    if foreign and whole_units(foreign["foreign_currency"]):
        over = foreign["tendered"] - Decimal(amount)
        if ZERO < over < foreign["foreign_rate"]:
            foreign = {**foreign, "tendered": Decimal(amount).quantize(CENT)}
    return foreign
