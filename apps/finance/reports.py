"""Everyday money tools: expenses, end-of-day cash count (Z report) and sales reports."""

from datetime import date
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.businessday import business_date, day_range
from apps.core.exceptions import BusinessError
from apps.core.forms import DateInput, StyledFormMixin
from apps.core.models import audit
from apps.outlets.models import Order, OrderLine

from .models import ZERO, Charge, DayClose, Expense, Payment, net
from .views import _range


class ExpenseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["business_date", "category", "description", "supplier", "amount", "method", "reference"]
        widgets = {"business_date": DateInput()}

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError(_("Enter an amount above zero."))
        return amount


@module_required("finance")
def expense_list(request):
    start, end = _range(request)
    qs = Expense.objects.filter(business_date__range=(start, end)).select_related("created_by")
    category = request.GET.get("category", "")
    if category:
        qs = qs.filter(category=category)
    total = qs.filter(voided=False).aggregate(t=Sum("amount"))["t"] or ZERO
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "finance/expenses.html",
        {
            "page_obj": page,
            "object_list": page.object_list,
            "start": start,
            "end": end,
            "total": total,
            "categories": Expense.Category.choices,
            "category": category,
        },
    )


@module_required("finance")
def expense_form(request, pk=None):
    expense = get_object_or_404(Expense, pk=pk, voided=False) if pk else None
    form = ExpenseForm(request.POST or None, instance=expense, initial={"business_date": business_date()})
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.pk:
            obj.created_by = request.user
        obj.save()
        audit(request.user, "expense.save", f"{obj.description} {obj.amount}", obj)
        messages.success(request, _("Expense saved."))
        if "add_another" in request.POST:
            return redirect("finance:expense_create")
        return redirect("finance:expenses")
    return render(request, "finance/expense_form.html", {"form": form, "object": expense})


@require_POST
@module_required("finance")
def expense_void(request, pk):
    expense = get_object_or_404(Expense, pk=pk, voided=False)
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, _("Give a reason for the void."))
    else:
        expense.voided, expense.void_reason, expense.voided_by, expense.voided_at = (
            True,
            reason[:255],
            request.user,
            timezone.now(),
        )
        expense.save(update_fields=["voided", "void_reason", "voided_by", "voided_at"])
        audit(request.user, "expense.void", f"{expense} – {reason}", expense)
        messages.success(request, _("Entry voided."))
    return redirect("finance:expenses")


# ---------- Day close / Z report ----------


def day_summary(day: date) -> dict:
    # Voids count on the day they were made (see VoidableQuerySet), so a closed day never changes.
    amount = net("amount", day)
    payments = Payment.objects.period(day)
    by_method = {m: ZERO for m in Payment.Method.values}
    for row in payments.values("method").annotate(t=amount):
        by_method[row["method"]] = row["t"]
    cash_expenses = (
        Expense.objects.period(day).filter(method=Payment.Method.CASH).aggregate(t=amount)["t"] or ZERO
    )
    charges = Charge.objects.period(day)
    departments = []
    acc = charges.filter(kind=Charge.Kind.ACCOMMODATION).aggregate(t=amount)["t"]
    if acc:
        departments.append((_("Accommodation"), acc))
    for row in charges.filter(kind=Charge.Kind.OUTLET).values("outlet__name").annotate(t=amount).order_by("-t"):
        if row["t"]:
            departments.append((row["outlet__name"], row["t"]))
    extras = charges.filter(kind=Charge.Kind.EXTRA).aggregate(t=amount)["t"]
    if extras:
        departments.append((_("Extras"), extras))
    staff = (
        payments.values("created_by__first_name", "created_by__last_name", "created_by__username")
        .annotate(t=amount, n=Count("id"))
        .order_by("-t")
    )
    since, until = day_range(day)
    receipts = Order.objects.filter(closed_at__gte=since, closed_at__lt=until, status=Order.Status.CLOSED)
    return {
        "by_method": by_method,
        "method_rows": [(label, by_method[value]) for value, label in Payment.Method.choices if by_method[value]],
        "cash": by_method[Payment.Method.CASH],
        "card": by_method[Payment.Method.CARD],
        "other": sum((v for k, v in by_method.items() if k not in (Payment.Method.CASH, Payment.Method.CARD)), ZERO),
        "received": sum(by_method.values(), ZERO),
        "cash_expenses": cash_expenses,
        "departments": departments,
        "revenue": charges.aggregate(t=amount)["t"] or ZERO,
        "staff": [
            {
                "name": f"{r['created_by__first_name']} {r['created_by__last_name']}".strip()
                or r["created_by__username"]
                or "—",
                "total": r["t"],
                "count": r["n"],
            }
            for r in staff
        ],
        "receipt_count": receipts.count(),
        "discounts": receipts.aggregate(t=Sum("discount"))["t"] or ZERO,
        "voids": Order.objects.filter(closed_at__gte=since, closed_at__lt=until, status=Order.Status.CANCELLED)
        .exclude(receipt_number="")
        .count(),
    }


class DayCloseForm(StyledFormMixin, forms.Form):
    opening_float = forms.DecimalField(
        label=_("Cash in the drawer at the start of the day"), min_value=0, decimal_places=2, initial=0
    )
    counted_cash = forms.DecimalField(label=_("Cash counted now"), min_value=0, decimal_places=2)
    notes = forms.CharField(label=_("Notes"), max_length=255, required=False)


@module_required("finance")
def day_close(request):
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = business_date()  # at 01:30 a night bar is still closing yesterday
    summary = day_summary(day)
    existing = DayClose.objects.filter(business_date=day).first()
    previous = DayClose.objects.filter(business_date__lt=day).first()
    initial = {"opening_float": existing.opening_float if existing else (previous.counted_cash if previous else ZERO)}
    if existing:
        initial.update(counted_cash=existing.counted_cash, notes=existing.notes)
    form = DayCloseForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            if existing and not request.user.is_manager:
                raise BusinessError(_("This day is already closed. Only a manager can close it again."))
            d = form.cleaned_data
            expected = d["opening_float"] + summary["cash"] - summary["cash_expenses"]
            obj, _created = DayClose.objects.update_or_create(
                business_date=day,
                defaults={
                    "opening_float": d["opening_float"],
                    "cash_sales": summary["cash"],
                    "cash_expenses": summary["cash_expenses"],
                    "expected_cash": expected,
                    "counted_cash": d["counted_cash"],
                    "card_total": summary["card"],
                    "other_total": summary["other"],
                    "revenue_total": summary["revenue"],
                    "notes": d["notes"],
                    "closed_by": request.user,
                },
            )
            audit(request.user, "day.close", f"{day}: expected {expected}, counted {d['counted_cash']}", obj)
            diff = obj.difference
            if diff == 0:
                messages.success(request, _("Day closed. The cash matches exactly."))
            else:
                messages.warning(request, _("Day closed with a difference of %(d)s.") % {"d": f"{diff:+.2f}"})
            return redirect(f"{request.path}?date={day.isoformat()}")
        except BusinessError as e:
            messages.error(request, str(e))
    expected_now = form["opening_float"].value() or 0
    try:
        expected_now = Decimal(str(expected_now)) + summary["cash"] - summary["cash_expenses"]
    except Exception:
        expected_now = summary["cash"] - summary["cash_expenses"]
    return render(
        request,
        "finance/day_close.html",
        {
            "day": day,
            "s": summary,
            "form": form,
            "existing": existing,
            "expected_now": expected_now,
            "history": DayClose.objects.all()[:14],
            "print_mode": request.GET.get("print") == "1",
        },
    )


# ---------- Sales reports ----------


@module_required("finance")
def sales(request):
    start, end = _range(request)
    since, until = day_range(start, end)
    lines = OrderLine.objects.filter(
        order__status=Order.Status.CLOSED, order__closed_at__gte=since, order__closed_at__lt=until
    )
    top_items = (
        lines.values("name", "order__outlet__name")
        .annotate(qty=Sum("quantity"), revenue=Sum(F("quantity") * F("unit_price")))
        .order_by("-revenue")[:30]
    )
    orders = Order.objects.filter(status=Order.Status.CLOSED, closed_at__gte=since, closed_at__lt=until)
    staff_totals = {}
    for o in orders.prefetch_related("lines"):
        key = o.opened_by_id
        staff_totals[key] = staff_totals.get(key, ZERO) + o.total
    staff_rows = []
    for o in (
        orders.values("opened_by_id", "opened_by__first_name", "opened_by__last_name", "opened_by__username")
        .annotate(n=Count("id"))
        .order_by()
    ):
        name = f"{o['opened_by__first_name']} {o['opened_by__last_name']}".strip() or o["opened_by__username"] or "—"
        total = staff_totals.get(o["opened_by_id"], ZERO)
        staff_rows.append({"name": name, "count": o["n"], "total": total, "avg": total / o["n"] if o["n"] else ZERO})
    staff_rows.sort(key=lambda r: -r["total"])
    hours = {h: ZERO for h in range(24)}
    for o in orders.only("closed_at", "discount").prefetch_related("lines"):
        hours[timezone.localtime(o.closed_at).hour] += o.total
    busy_hours = [(h, v) for h, v in hours.items() if v]
    hour_max = max([v for _h, v in busy_hours] + [Decimal("1")])
    revenue = sum((r["total"] for r in staff_rows), ZERO)
    return render(
        request,
        "finance/sales.html",
        {
            "start": start,
            "end": end,
            "top_items": top_items,
            "staff_rows": staff_rows,
            "busy_hours": busy_hours,
            "hour_max": hour_max,
            "order_count": orders.count(),
            "revenue": revenue,
            "avg_bill": revenue / orders.count() if orders.count() else ZERO,
            "discounts": orders.aggregate(t=Sum("discount"))["t"] or ZERO,
        },
    )
