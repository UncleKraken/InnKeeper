"""Payroll pages: the month's gross pay, bonuses and advances, public holidays, and approving a month."""

from datetime import date, timedelta

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.forms import DateInput, StyledFormMixin
from apps.core.models import HotelSettings, audit

from . import payroll
from .models import PayAdjustment, PayrollMonth, PublicHoliday
from .views import TABS, team


def _month(request) -> date:
    raw = request.GET.get("month") or request.POST.get("month") or ""
    try:
        y, m = (int(x) for x in raw.split("-")[:2])
        return date(y, m, 1)
    except ValueError:
        today = timezone.localdate()
        first = today.replace(day=1)
        # Early in the month you pay last month.
        return (first - timedelta(days=1)).replace(day=1) if today.day <= 10 else first


class RatesForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = ["payroll_overtime_percent", "payroll_night_percent", "payroll_holiday_percent"]


class AdjustmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PayAdjustment
        fields = ["user", "amount", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = team()
        self.fields["user"].label = _("Person")


@module_required("management")
def payroll_page(request):
    month = _month(request)
    approved = PayrollMonth.objects.filter(month=month).first()
    if approved:
        rows = payroll.thawed(approved.rows)
    else:
        rows = payroll.calculate(month)
    if request.GET.get("format") == "xlsx":
        return _xlsx(rows, month)
    hs = HotelSettings.load()
    first, last = payroll.month_bounds(month)
    return render(
        request,
        "staff/payroll.html",
        {
            "rows": rows,
            "totals": payroll.totals(rows),
            "month": month,
            "month_value": month.strftime("%Y-%m"),
            "approved": approved,
            "rates_form": RatesForm(instance=hs),
            "adjustment_form": AdjustmentForm(),
            "holidays": PublicHoliday.objects.filter(date__range=(first, last)),
            "year_has_holidays": PublicHoliday.objects.filter(date__year=month.year).exists(),
            "tabs": TABS,
            "tab": "staff:payroll",
        },
    )


def _back(month: date):
    return redirect(f"{reverse('staff:payroll')}?month={month:%Y-%m}")


@require_POST
@module_required("management")
def rates(request):
    form = RatesForm(request.POST, instance=HotelSettings.load())
    if form.is_valid():
        form.save()
        audit(request.user, "payroll.rates", ", ".join(f"{k}={v}" for k, v in form.cleaned_data.items()))
        messages.success(request, _("Settings saved."))
    else:
        messages.error(request, _("Check the numbers: from 0 to 300."))
    return _back(_month(request))


@require_POST
@module_required("management")
def adjustment(request):
    month = _month(request)
    if PayrollMonth.objects.filter(month=month).exists():
        messages.error(request, _("This month is approved. Reopen it first."))
        return _back(month)
    if request.POST.get("delete"):
        a = get_object_or_404(PayAdjustment, pk=request.POST["delete"], month=month)
        audit(request.user, "payroll.adjustment_delete", f"{a.user} {a.amount} {a.note}")
        a.delete()
        return _back(month)
    form = AdjustmentForm(request.POST)
    if form.is_valid():
        a = form.save(commit=False)
        a.month, a.created_by = month, request.user
        a.save()
        audit(request.user, "payroll.adjustment", f"{a.user} {month:%m.%Y} {a.amount} {a.note}")
        messages.success(request, _("Added to %(name)s's pay.") % {"name": a.user})
    else:
        messages.error(request, " ".join(str(e) for errs in form.errors.values() for e in errs))
    return _back(month)


@require_POST
@module_required("management")
def approve(request):
    month = _month(request)
    if request.POST.get("reopen"):
        PayrollMonth.objects.filter(month=month).delete()
        audit(request.user, "payroll.reopen", f"{month:%m.%Y}")
        messages.success(request, _("The month is open again: the numbers follow the clock-ins."))
        return _back(month)
    rows = payroll.calculate(month)
    PayrollMonth.objects.update_or_create(month=month, defaults={"rows": payroll.frozen(rows), "approved_by": request.user})
    audit(request.user, "payroll.approve", f"{month:%m.%Y}: {payroll.totals(rows)['gross']}")
    messages.success(request, _("Payroll approved. These numbers stay as they are, even if clock-ins change later."))
    return _back(month)


class HolidayForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PublicHoliday
        fields = ["date", "name"]
        widgets = {"date": DateInput()}


@module_required("management")
def holidays(request):
    year = int(request.GET.get("year") or timezone.localdate().year)
    form = HolidayForm(request.POST or None)
    if request.method == "POST":
        if request.POST.get("fill"):
            n = payroll.add_albanian_holidays(year)
            messages.success(request, _("%(n)s holidays added for %(y)s. Add the Bajram days when the government announces them.") % {"n": n, "y": year})
            return redirect(f"{reverse('staff:holidays')}?year={year}")
        if request.POST.get("delete"):
            get_object_or_404(PublicHoliday, pk=request.POST["delete"]).delete()
            return redirect(f"{reverse('staff:holidays')}?year={year}")
        if form.is_valid():
            h = form.save()
            audit(request.user, "payroll.holiday", str(h))
            return redirect(f"{reverse('staff:holidays')}?year={h.date.year}")
    return render(
        request,
        "staff/holidays.html",
        {"form": form, "year": year, "days": PublicHoliday.objects.filter(date__year=year), "tabs": TABS, "tab": "staff:payroll"},
    )


def _xlsx(rows, month):
    from apps.core import spreadsheet

    pay_labels = {"monthly": _("Monthly"), "hourly": _("Hourly"), "": ""}
    sheet = spreadsheet.Sheet(
        _("Payroll"),
        [_("Name"), _("Position"), _("Pay"), _("Rate"), _("Days"), _("Hours"), _("Overtime hours"), _("Night hours"),
         _("Holiday hours"), _("Base"), _("Overtime"), _("Night"), _("Holiday"), _("Bonuses / advances"), _("Gross"), "IBAN"],
        [
            [r["name"], r["position"], pay_labels.get(r["pay_type"], ""), r["rate"], r["days"], r["hours"], r["overtime_hours"],
             r["night_hours"], r["holiday_hours"], r["base"], r["extras"]["overtime"], r["extras"]["night"], r["extras"]["holiday"],
             r["adjustments_total"], r["gross"], r["iban"]]
            for r in rows
        ],
        money=(3, 9, 10, 11, 12, 13, 14),
    )
    return spreadsheet.response(f"payroll-{month:%Y-%m}", sheet)
