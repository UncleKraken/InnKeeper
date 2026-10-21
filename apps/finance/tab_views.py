"""Screens for customer accounts (tabs) and staff shifts."""

from decimal import Decimal, InvalidOperation
from functools import wraps

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import can_access
from apps.core.exceptions import BusinessError
from apps.core.forms import StyledFormMixin
from apps.core.models import audit

from . import tabs
from .models import CustomerAccount, Payment, Shift


def any_module(*modules):
    """Open to staff who may use any of these areas (e.g. the bar or the office)."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            if not any(can_access(request.user, m) for m in modules):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def _amount(value) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return None


class AccountForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CustomerAccount
        fields = ["name", "phone", "credit_limit", "opening_balance", "note", "is_active"]


# ---------- Customer accounts ----------


@any_module("outlets", "finance")
def accounts(request):
    q = request.GET.get("q", "").strip()
    show_closed = request.GET.get("closed") == "1"
    qs = CustomerAccount.objects.all()
    if not show_closed:
        qs = qs.filter(is_active=True)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    rows = tabs.accounts_with_balances(qs)
    if request.GET.get("sort") != "name":
        rows.sort(key=lambda a: a.current_balance, reverse=True)
    return render(
        request,
        "finance/accounts.html",
        {"rows": rows, "q": q, "total": sum((a.current_balance for a in rows), Decimal("0")), "show_closed": show_closed},
    )


@any_module("outlets", "finance")
def account_form(request, pk=None):
    if not request.user.is_manager:
        raise PermissionDenied
    account = get_object_or_404(CustomerAccount, pk=pk) if pk else None
    form = AccountForm(request.POST or None, instance=account)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.pk:
            obj.created_by = request.user
        obj.save()
        audit(request.user, "account.save", f"{obj.name} (limit {obj.credit_limit}, before {obj.opening_balance})", obj)
        messages.success(request, _("Saved %(obj)s.") % {"obj": obj})
        return redirect("finance:account", pk=obj.pk)
    return render(request, "finance/account_form.html", {"form": form, "object": account})


@any_module("outlets", "finance")
def account_detail(request, pk):
    account = get_object_or_404(CustomerAccount, pk=pk)
    rows = tabs.statement(account)
    balance = rows[-1]["balance"] if rows else account.opening_balance
    return render(
        request,
        "finance/account_detail.html",
        {
            "account": account,
            "rows": rows,
            "balance": balance,
            "methods": [(v, label) for v, label in Payment.Method.choices if v != Payment.Method.ONLINE],
            "print": request.GET.get("print") == "1",
        },
    )


@require_POST
@any_module("outlets", "finance")
def account_pay(request, pk):
    account = get_object_or_404(CustomerAccount, pk=pk)
    amount = _amount(request.POST.get("amount", ""))
    try:
        if amount is None:
            raise BusinessError(_("Enter an amount."))
        tabs.pay_account(
            account, amount=amount, method=request.POST.get("method", Payment.Method.CASH), user=request.user,
            reference=request.POST.get("reference", ""),
        )
        messages.success(request, _("Payment recorded. %(name)s now owes %(b)s.") % {"name": account.name, "b": f"{account.balance:.2f}"})
    except BusinessError as e:
        messages.error(request, str(e))
    return redirect("finance:account", pk=account.pk)


# ---------- Shifts ----------


@any_module("outlets", "frontdesk", "finance")
def my_shift(request):
    shift = tabs.open_shift_for(request.user)
    ctx = {"shift": shift}
    if shift:
        ctx["summary"] = tabs.summary(shift)
    ctx["recent"] = Shift.objects.filter(user=request.user, closed_at__isnull=False)[:5]
    return render(request, "finance/shift.html", ctx)


@require_POST
@any_module("outlets", "frontdesk", "finance")
def shift_start(request):
    try:
        tabs.start_shift(request.user, _amount(request.POST.get("opening_float", "0") or "0") or Decimal("0"))
        messages.success(request, _("Shift started. Payments you take are counted in it."))
    except BusinessError as e:
        messages.error(request, str(e))
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "finance:my_shift")


@require_POST
@any_module("outlets", "frontdesk", "finance")
def shift_end(request, pk):
    shift = get_object_or_404(Shift, pk=pk)
    counted = _amount(request.POST.get("counted", ""))
    try:
        if counted is None:
            raise BusinessError(_("Count the cash and enter the amount."))
        tabs.end_shift(shift, counted=counted, user=request.user, notes=request.POST.get("notes", ""),
                       counted_second=_amount(request.POST.get("counted_second", "")))
    except BusinessError as e:
        messages.error(request, str(e))
        return redirect("finance:my_shift")
    return redirect("finance:shift_report", pk=shift.pk)


@any_module("outlets", "frontdesk", "finance")
def shift_report(request, pk):
    shift = get_object_or_404(Shift.objects.select_related("user"), pk=pk)
    if shift.user_id != request.user.pk and not (request.user.is_manager or can_access(request.user, "finance")):
        raise PermissionDenied
    payments = shift.payments.select_related("order", "order__outlet", "folio__reservation__room", "account")
    return render(
        request,
        "finance/shift_report.html",
        {"shift": shift, "summary": tabs.summary(shift), "payments": payments.order_by("created_at")},
    )


@any_module("finance")
def shifts(request):
    rows = Shift.objects.select_related("user")[:200]
    return render(request, "finance/shifts.html", {"rows": rows})
