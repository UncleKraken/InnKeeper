import csv
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.permissions import module_required
from apps.frontdesk.models import Reservation, Room

from .models import ZERO, Charge, Expense, Folio, Payment


def _range(request) -> tuple[date, date]:
    today = timezone.localdate()
    default_start = today.replace(day=1)
    try:
        start = date.fromisoformat(request.GET.get("from", ""))
    except ValueError:
        start = default_start
    try:
        end = date.fromisoformat(request.GET.get("to", ""))
    except ValueError:
        end = today
    if end < start:
        start, end = end, start
    if (end - start).days > 366:
        start = end - timedelta(days=366)
    return start, end


def _nights_sold(start: date, end: date) -> int:
    """Room nights occupied between start and end (inclusive), from actual stays."""
    stays = Reservation.objects.filter(
        status__in=[Reservation.Status.CHECKED_IN, Reservation.Status.CHECKED_OUT],
        arrival__lte=end,
        departure__gt=start,
    ).only("arrival", "departure")
    last_night = end + timedelta(days=1)
    return sum(max(0, (min(r.departure, last_night) - max(r.arrival, start)).days) for r in stays)


@module_required("finance")
def dashboard(request):
    start, end = _range(request)
    charges = Charge.objects.active().filter(business_date__range=(start, end))
    payments = Payment.objects.active().filter(business_date__range=(start, end))

    total = charges.aggregate(t=Sum("amount"))["t"] or ZERO
    accommodation = charges.filter(kind=Charge.Kind.ACCOMMODATION).aggregate(t=Sum("amount"), n=Sum("quantity"))

    departments = [
        {"name": _("Accommodation"), "amount": accommodation["t"] or ZERO},
    ]
    for row in (
        charges.filter(kind=Charge.Kind.OUTLET)
        .values("outlet__name")
        .annotate(amount=Sum("amount"), count=Count("id"))
        .order_by("-amount")
    ):
        departments.append({"name": row["outlet__name"], "amount": row["amount"]})
    extras = charges.filter(kind=Charge.Kind.EXTRA).aggregate(t=Sum("amount"))["t"]
    if extras:
        departments.append({"name": _("Extras"), "amount": extras})
    departments = [d for d in departments if d["amount"]]

    days = (end - start).days + 1
    per_day = {row["business_date"]: row["t"] for row in charges.values("business_date").annotate(t=Sum("amount"))}
    daily = [
        {"date": start + timedelta(days=i), "amount": per_day.get(start + timedelta(days=i), ZERO)} for i in range(days)
    ]
    daily_max = max([d["amount"] for d in daily] + [Decimal("1")])

    by_method = list(payments.values("method").annotate(t=Sum("amount")).order_by("-t"))
    method_labels = dict(Payment.Method.choices)
    for row in by_method:
        row["label"] = method_labels.get(row["method"], row["method"])
    received = payments.aggregate(t=Sum("amount"))["t"] or ZERO

    rooms = Room.objects.filter(is_active=True).count()
    nights_sold = _nights_sold(start, end)
    available = rooms * days
    acc_nights = accommodation["n"] or 0
    kpis = {
        "occupancy": round(nights_sold * 100 / available, 1) if available else 0,
        "adr": (accommodation["t"] / acc_nights) if acc_nights else ZERO,
        "revpar": ((accommodation["t"] or ZERO) / available) if available else ZERO,
        "nights_sold": nights_sold,
    }

    expenses = Expense.objects.active().filter(business_date__range=(start, end))
    expenses_total = expenses.aggregate(t=Sum("amount"))["t"] or ZERO
    category_labels = dict(Expense.Category.choices)
    expense_rows = [
        {"label": category_labels.get(r["category"], r["category"]), "amount": r["t"]}
        for r in expenses.values("category").annotate(t=Sum("amount")).order_by("-t")
    ]

    outstanding = []
    for folio in Folio.objects.filter(status=Folio.Status.OPEN).select_related(
        "reservation__guest", "reservation__room"
    ):
        balance = folio.balance
        if balance > 0:
            outstanding.append({"folio": folio, "balance": balance})
    outstanding.sort(key=lambda x: -x["balance"])

    return render(
        request,
        "finance/dashboard.html",
        {
            "start": start,
            "end": end,
            "total": total,
            "received": received,
            "departments": departments,
            "daily": daily,
            "daily_max": daily_max,
            "by_method": by_method,
            "kpis": kpis,
            "outstanding": outstanding[:25],
            "outstanding_total": sum((o["balance"] for o in outstanding), ZERO),
            "show_day_labels": days <= 31,
            "expenses_total": expenses_total,
            "expense_rows": expense_rows,
            "profit": total - expenses_total,
        },
    )


@module_required("finance")
def ledger(request):
    start, end = _range(request)
    kind = request.GET.get("type", "charges")
    if kind == "payments":
        rows = Payment.objects.filter(business_date__range=(start, end)).select_related(
            "folio__reservation__guest", "order__outlet", "created_by"
        )
    else:
        kind = "charges"
        rows = Charge.objects.filter(business_date__range=(start, end)).select_related(
            "folio__reservation__guest", "outlet", "created_by"
        )
    rows = rows.order_by("-business_date", "-id")
    if request.GET.get("format") == "csv":
        return _csv(rows, kind, start, end)
    return render(
        request,
        "finance/ledger.html",
        {"rows": rows[:500], "kind": kind, "start": start, "end": end, "count": rows.count()},
    )


def _csv(rows, kind, start, end) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="innkeeper-{kind}-{start}-{end}.csv"'
    response.write("﻿")  # so Excel opens UTF-8 (ë, ç) correctly
    writer = csv.writer(response)
    if kind == "payments":
        writer.writerow(
            [
                "date",
                "id",
                "method",
                "amount",
                "reference",
                "folio",
                "guest",
                "order",
                "outlet",
                "staff",
                "voided",
                "void_reason",
            ]
        )
        for p in rows:
            writer.writerow(
                [
                    p.business_date,
                    p.pk,
                    p.method,
                    p.amount,
                    p.reference,
                    p.folio.number if p.folio_id else "",
                    p.folio.reservation.guest if p.folio_id else "",
                    p.order_id or "",
                    p.order.outlet if p.order_id else "",
                    p.created_by or "",
                    int(p.voided),
                    p.void_reason,
                ]
            )
    else:
        writer.writerow(
            [
                "date",
                "id",
                "department",
                "description",
                "quantity",
                "unit_price",
                "amount",
                "folio",
                "guest",
                "order",
                "staff",
                "voided",
                "void_reason",
            ]
        )
        for c in rows:
            writer.writerow(
                [
                    c.business_date,
                    c.pk,
                    c.department,
                    c.description,
                    c.quantity,
                    c.unit_price,
                    c.amount,
                    c.folio.number if c.folio_id else "",
                    c.folio.reservation.guest if c.folio_id else "",
                    c.order_id or "",
                    c.created_by or "",
                    int(c.voided),
                    c.void_reason,
                ]
            )
    return response
