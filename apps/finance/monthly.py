"""
The month for the accountant: one printable page (save it as PDF from the print window) and an Excel file
with sales by department and VAT rate, money received, expenses, profit, and every day of the month.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.permissions import module_required
from apps.core.businessday import business_date, day_range
from apps.core.models import HotelSettings

from .models import ZERO, Charge, DayClose, Expense, Payment, net

CENT = Decimal("0.01")


def month_bounds(value: str) -> tuple[date, date]:
    try:
        y, m = (int(x) for x in value.split("-")[:2])
        start = date(y, m, 1)
    except (ValueError, AttributeError):
        today = business_date()
        first = today.replace(day=1)
        start = (first - timedelta(days=1)).replace(day=1) if today.day <= 10 else first  # early in the month: last month
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    return start, end


def report(start: date, end: date) -> dict:
    from apps.outlets.models import Order

    hs = HotelSettings.load()
    amount = net("amount", start, end)
    charges = Charge.objects.period(start, end)
    departments = []
    acc = charges.filter(kind=Charge.Kind.ACCOMMODATION).aggregate(t=amount)["t"] or ZERO
    if acc:
        departments.append((_("Accommodation"), acc))
    for row in charges.filter(kind=Charge.Kind.OUTLET).values("outlet__name").annotate(t=amount).order_by("-t"):
        if row["t"]:
            departments.append((row["outlet__name"], row["t"]))
    extras = charges.filter(kind=Charge.Kind.EXTRA).aggregate(t=amount)["t"] or ZERO
    if extras:
        departments.append((_("Extras"), extras))
    revenue = charges.aggregate(t=amount)["t"] or ZERO

    vat_rows = []
    if hs.charges_vat:
        groups = {}
        acc_rate, rate = hs.vat_rate_accommodation, hs.vat_rate
        groups[acc_rate] = groups.get(acc_rate, ZERO) + acc
        groups[rate] = groups.get(rate, ZERO) + (revenue - acc)
        for r, gross in sorted(groups.items(), key=lambda x: -x[0]):
            if gross:
                vat = (gross * r / (100 + r)).quantize(CENT)
                vat_rows.append({"rate": r.normalize(), "gross": gross, "net": gross - vat, "vat": vat})

    payments = Payment.objects.period(start, end)
    labels = dict(Payment.Method.choices)
    methods = [
        (labels.get(r["method"], r["method"]), r["t"])
        for r in payments.exclude(method=Payment.Method.VOUCHER).values("method").annotate(t=amount).order_by("-t")
        if r["t"]
    ]
    received = sum((t for _l, t in methods), ZERO)
    vouchers_sold = payments.filter(voucher__isnull=False).exclude(method=Payment.Method.VOUCHER).aggregate(t=amount)["t"] or ZERO
    vouchers_spent = payments.filter(method=Payment.Method.VOUCHER).aggregate(t=amount)["t"] or ZERO
    tips = Payment.objects.active().filter(business_date__range=(start, end)).aggregate(t=Sum("tip"))["t"] or ZERO

    expenses = Expense.objects.period(start, end)
    cat_labels = dict(Expense.Category.choices)
    expense_rows = [
        (cat_labels.get(r["category"], r["category"]), r["t"])
        for r in expenses.values("category").annotate(t=amount).order_by("-t")
        if r["t"]
    ]
    expenses_total = sum((t for _l, t in expense_rows), ZERO)

    # Every day: sales, money by kind, expenses and the cash count.
    closes = {d.business_date: d for d in DayClose.objects.filter(business_date__range=(start, end))}
    days = []
    d = start
    while d <= end:
        a = net("amount", d)
        p = Payment.objects.period(d).exclude(method=Payment.Method.VOUCHER)
        cash = p.filter(method=Payment.Method.CASH).aggregate(t=a)["t"] or ZERO
        card = p.filter(method__in=[Payment.Method.CARD, Payment.Method.ONLINE]).aggregate(t=a)["t"] or ZERO
        other = (p.aggregate(t=a)["t"] or ZERO) - cash - card
        sales = Charge.objects.period(d).aggregate(t=a)["t"] or ZERO
        exp = Expense.objects.period(d).aggregate(t=a)["t"] or ZERO
        close = closes.get(d)
        days.append(
            {"date": d, "sales": sales, "cash": cash, "card": card, "other": other, "expenses": exp,
             "difference": close.difference if close else None, "closed": close is not None}
        )
        d += timedelta(days=1)

    since, until = day_range(start, end)
    bills = Order.objects.filter(closed_at__gte=since, closed_at__lt=until)
    closed = bills.filter(status=Order.Status.CLOSED)
    voided = bills.filter(status=Order.Status.CANCELLED).exclude(receipt_number="")
    fiscal = {}
    if hs.fiscal_on:
        from apps.fiscal.models import FiscalDocument

        docs = FiscalDocument.objects.filter(created_at__gte=since, created_at__lt=until)
        fiscal = {r["status"]: r["n"] for r in docs.values("status").annotate(n=Count("id"))}
    return {
        "start": start,
        "end": end,
        "departments": departments,
        "revenue": revenue,
        "vat_rows": vat_rows,
        "vat_total": sum((r["vat"] for r in vat_rows), ZERO),
        "methods": methods,
        "received": received,
        "vouchers_sold": vouchers_sold,
        "vouchers_spent": vouchers_spent,
        "tips": tips,
        "expense_rows": expense_rows,
        "expenses_total": expenses_total,
        "profit": revenue - expenses_total,
        "days": days,
        "days_not_closed": sum(1 for x in days if not x["closed"] and (x["sales"] or x["cash"])),
        "cash_difference": sum((x["difference"] for x in days if x["difference"]), ZERO),
        "bill_count": closed.count(),
        "discounts": closed.aggregate(t=Sum("discount"))["t"] or ZERO,
        "voided_count": voided.count(),
        "fiscal": fiscal,
        "fiscal_registered": fiscal.get("registered", 0),
        "fiscal_missing": fiscal.get("pending", 0) + fiscal.get("failed", 0),
    }


@module_required("finance")
def monthly(request):
    start, end = month_bounds(request.GET.get("month", ""))
    data = report(start, end)
    if request.GET.get("format") == "xlsx":
        return _xlsx(data)
    return render(
        request,
        "finance/monthly.html",
        {**data, "month_value": start.strftime("%Y-%m"), "printed_at": timezone.localtime()},
    )


def _xlsx(r):
    from apps.core import spreadsheet

    summary = [[name, amount] for name, amount in r["departments"]]
    summary += [[_("Sales"), r["revenue"]], ["", None]]
    summary += [[label, amount] for label, amount in r["methods"]] + [[_("Money received"), r["received"]], ["", None]]
    summary += [[label, amount] for label, amount in r["expense_rows"]] + [[_("Expenses"), r["expenses_total"]], [_("Profit"), r["profit"]]]
    sheets = [
        spreadsheet.Sheet(_("Summary"), [r["start"].strftime("%m.%Y"), ""], summary, money=(1,), widths={0: 34, 1: 16}),
        spreadsheet.Sheet(
            _("Days"),
            [_("Date"), _("Sales"), _("Cash"), _("Card"), _("Other"), _("Expenses"), _("Cash difference")],
            ([x["date"], x["sales"], x["cash"], x["card"], x["other"], x["expenses"], x["difference"]] for x in r["days"]),
            money=(1, 2, 3, 4, 5, 6),
        ),
    ]
    if r["vat_rows"]:
        sheets.append(
            spreadsheet.Sheet(
                _("VAT"),
                [_("VAT rate"), _("With VAT"), _("Without VAT"), _("VAT")],
                ([f"{x['rate']}%", x["gross"], x["net"], x["vat"]] for x in r["vat_rows"]),
                money=(1, 2, 3),
            )
        )
    return spreadsheet.response(f"month-{r['start']:%Y-%m}", *sheets)
