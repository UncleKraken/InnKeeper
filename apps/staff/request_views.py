"""Leave and swap requests: staff ask from "My hours", managers decide on "Requests"."""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.accounts.permissions import module_required
from apps.core.exceptions import BusinessError
from apps.core.forms import DateInput, StyledFormMixin

from . import requests as svc
from .models import LeaveRequest, ScheduledShift, SwapRequest
from .views import TABS


class LeaveForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ["kind", "start", "end", "note"]
        widgets = {"start": DateInput(), "end": DateInput()}


def _run(request, fn, ok_message):
    try:
        fn()
        messages.success(request, ok_message)
    except BusinessError as e:
        messages.error(request, str(e))


@require_POST
@login_required
def leave_ask(request):
    form = LeaveForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        _run(request, lambda: svc.ask_leave(request.user, kind=d["kind"], start=d["start"], end=d["end"], note=d["note"]),
             _("Request sent. A manager will answer it."))
    else:
        messages.error(request, " ".join(str(e) for errs in form.errors.values() for e in errs))
    return redirect("staff:my_hours")


@require_POST
@login_required
def leave_cancel(request, pk):
    req = get_object_or_404(LeaveRequest, pk=pk, user=request.user)
    _run(request, lambda: svc.cancel_leave(req, request.user), _("Request cancelled."))
    return redirect("staff:my_hours")


@require_POST
@login_required
def swap_ask(request):
    shift = get_object_or_404(ScheduledShift, pk=request.POST.get("shift"), user=request.user)
    colleague = User.objects.filter(pk=request.POST.get("to_user") or 0, is_active=True).first()
    _run(request, lambda: svc.ask_swap(shift, request.user, colleague, request.POST.get("note", "")),
         _("Asked %(name)s. After they agree, a manager approves the change.") % {"name": colleague or ""})
    return redirect("staff:my_hours")


@require_POST
@login_required
def swap_answer(request, pk):
    swap = get_object_or_404(SwapRequest, pk=pk, to_user=request.user)
    agree = request.POST.get("agree") == "1"
    _run(request, lambda: svc.colleague_answer(swap, request.user, agree=agree),
         _("Thanks. A manager will approve the change.") if agree else _("Answer sent."))
    return redirect("staff:my_hours")


@require_POST
@login_required
def swap_cancel(request, pk):
    swap = get_object_or_404(SwapRequest, pk=pk, from_user=request.user)
    _run(request, lambda: svc.cancel_swap(swap, request.user), _("Request cancelled."))
    return redirect("staff:my_hours")


def my_requests_context(user) -> dict:
    today = timezone.localdate()
    return {
        "leave_form": LeaveForm(),
        "leave_balance": svc.balance(user),
        "my_leave": LeaveRequest.objects.filter(user=user, end__gte=today.replace(month=1, day=1)).order_by("-start")[:12],
        "incoming_swaps": SwapRequest.objects.filter(to_user=user, status=SwapRequest.Status.ASKED).select_related("shift", "from_user"),
        "colleagues": User.objects.filter(is_active=True).exclude(pk=user.pk).order_by("first_name", "username"),
        "open_swaps": {
            s.shift_id: s
            for s in SwapRequest.objects.filter(from_user=user, status__in=[SwapRequest.Status.ASKED, SwapRequest.Status.AGREED]).select_related("to_user")
        },
    }


# ---------- Managers ----------


@module_required("management")
def requests_page(request):
    leave = LeaveRequest.objects.filter(status=LeaveRequest.Status.PENDING).select_related("user").order_by("start")
    for r in leave:
        r.days = r.working_days()
        r.balance = svc.balance(r.user, r.start.year) if r.kind == LeaveRequest.Kind.ANNUAL else None
        r.clashes = ScheduledShift.objects.filter(user=r.user, date__range=(r.start, r.end)).count()
    swaps = SwapRequest.objects.filter(status=SwapRequest.Status.AGREED).select_related("shift", "shift__position", "from_user", "to_user")
    decided = sorted(
        list(LeaveRequest.objects.exclude(status=LeaveRequest.Status.PENDING).exclude(decided_at=None).select_related("user", "decided_by").order_by("-decided_at")[:10])
        + list(SwapRequest.objects.exclude(decided_at=None).select_related("shift", "from_user", "to_user", "decided_by").order_by("-decided_at")[:10]),
        key=lambda x: x.decided_at,
        reverse=True,
    )[:15]
    upcoming = LeaveRequest.objects.filter(status=LeaveRequest.Status.APPROVED, end__gte=timezone.localdate()).select_related("user").order_by("start")[:20]
    return render(
        request,
        "staff/requests.html",
        {"leave": leave, "swaps": swaps, "decided": decided, "upcoming": upcoming, "tabs": TABS, "tab": "staff:requests"},
    )


@require_POST
@module_required("management")
def leave_decide(request, pk):
    req = get_object_or_404(LeaveRequest, pk=pk)
    approve = request.POST.get("approve") == "1"
    _run(request, lambda: svc.decide_leave(req, request.user, approve=approve, reason=request.POST.get("reason", "")),
         _("Leave approved.") if approve else _("Leave declined."))
    return redirect("staff:requests")


@require_POST
@module_required("management")
def swap_decide(request, pk):
    swap = get_object_or_404(SwapRequest, pk=pk)
    approve = request.POST.get("approve") == "1"
    _run(request, lambda: svc.manager_decide(swap, request.user, approve=approve),
         _("Shift moved on the schedule.") if approve else _("Swap declined."))
    return redirect("staff:requests")
