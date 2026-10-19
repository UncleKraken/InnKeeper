"""
The tourist tax ("taksa e turizmit / e qëndrimit"): a local tax the municipality sets on overnight stays.

The business adds it to the guest's bill and pays it to the municipality every month (usually by the
5th of the next month, with the list of guests). It is not the business's income and carries no VAT,
so it is left out of sales, VAT and the fiscal invoice and shown here on its own.
"""

from collections import defaultdict
from datetime import date, timedelta

from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.permissions import module_required

from .models import ZERO, Charge, net
from .monthly import month_bounds


def due_date(start: date) -> date:
    """The 5th of the month after."""
    return (start.replace(day=28) + timedelta(days=5)).replace(day=5)


def report(start: date, end: date) -> dict:
    charges = Charge.objects.period(start, end).filter(kind=Charge.Kind.TOURIST_TAX)
    amount = net("amount", start, end)
    units = net("quantity", start, end, integer=True)
    stays = defaultdict(lambda: {"amount": ZERO, "units": 0})
    for row in charges.values("reservation").annotate(t=amount, n=units):
        stays[row["reservation"]]["amount"] += row["t"] or ZERO
        stays[row["reservation"]]["units"] += row["n"] or 0
    from apps.frontdesk.models import Reservation

    rows = []
    for res in Reservation.objects.filter(pk__in=[k for k in stays if k]).select_related("guest", "room").order_by("arrival", "id"):
        s = stays[res.pk]
        if not s["amount"]:
            continue
        rows.append({"reservation": res, "guest": res.guest, "persons": res.adults + (res.children or 0), **s})
    return {
        "start": start,
        "end": end,
        "rows": rows,
        "total": sum((r["amount"] for r in rows), ZERO),
        "units": sum(r["units"] for r in rows),
        "due": due_date(start),
    }


@module_required("finance")
def tourist_tax(request):
    start, end = month_bounds(request.GET.get("month", ""))
    data = report(start, end)
    if request.GET.get("format") == "xlsx":
        return _xlsx(data)
    return render(
        request,
        "finance/tourist_tax.html",
        {**data, "month_value": start.strftime("%Y-%m"), "printed_at": timezone.localtime(), "overdue": timezone.localdate() > data["due"]},
    )


def _xlsx(d):
    from apps.core import spreadsheet

    sheet = spreadsheet.Sheet(
        _("Tourist tax"),
        [_("Guest"), _("Nationality"), _("Document"), _("Room"), _("Arrival"), _("Departure"), _("Guests"),
         _("Charged (guest-nights)"), _("Amount")],
        [
            [r["guest"].full_name, r["guest"].nationality, r["guest"].document_number, r["reservation"].room.number,
             r["reservation"].arrival, r["reservation"].departure, r["persons"], r["units"], r["amount"]]
            for r in d["rows"]
        ]
        + [[_("Total"), "", "", "", "", "", "", d["units"], d["total"]]],
        money=(8,),
    )
    return spreadsheet.response(f"tourist-tax-{d['start']:%Y-%m}", sheet)
