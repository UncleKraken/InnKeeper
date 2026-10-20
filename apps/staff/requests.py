"""
Leave and shift swaps.

Leave: a member of staff asks for days off (annual, sick, unpaid, other); a manager approves or
declines. Approved leave shows on the schedule and is not counted as "did not come".

Swaps: someone asks a colleague to take one of their planned shifts. The colleague agrees first, then a
manager approves, and only then does the shift change hands on the schedule.
"""

from datetime import date

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import BusinessError
from apps.core.models import audit

from .models import EmployeeProfile, LeaveRequest, PublicHoliday, ScheduledShift, SwapRequest

OPEN_LEAVE = (LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED)


# ---------- Leave ----------


def ask_leave(user, *, kind: str, start: date, end: date, note: str = "") -> LeaveRequest:
    if end < start:
        raise BusinessError(_("The last day is before the first day."))
    if (end - start).days > 120:
        raise BusinessError(_("That is more than four months. Please talk to a manager."))
    clash = LeaveRequest.objects.filter(user=user, status__in=OPEN_LEAVE, start__lte=end, end__gte=start).first()
    if clash:
        raise BusinessError(_("You already asked for leave on some of these days (%(d)s).") % {"d": f"{clash.start:%d.%m}–{clash.end:%d.%m}"})
    req = LeaveRequest.objects.create(user=user, kind=kind, start=start, end=end, note=note.strip()[:200])
    audit(user, "leave.ask", str(req), req)
    return req


@transaction.atomic
def decide_leave(req: LeaveRequest, manager, *, approve: bool, reason: str = "") -> LeaveRequest:
    req = LeaveRequest.objects.select_for_update().get(pk=req.pk)
    if req.status != LeaveRequest.Status.PENDING:
        raise BusinessError(_("Someone has already answered this request."))
    req.status = LeaveRequest.Status.APPROVED if approve else LeaveRequest.Status.DECLINED
    req.decided_by, req.decided_at, req.reason = manager, timezone.now(), reason.strip()[:200]
    req.save(update_fields=["status", "decided_by", "decided_at", "reason"])
    audit(manager, "leave.approve" if approve else "leave.decline", str(req), req)
    return req


def cancel_leave(req: LeaveRequest, user) -> None:
    """The person cancels their own request, before the leave starts."""
    if req.user_id != user.pk:
        raise BusinessError(_("Only your own requests."))
    started = req.status == LeaveRequest.Status.APPROVED and req.start <= timezone.localdate()
    if req.status not in OPEN_LEAVE or started:
        raise BusinessError(_("Leave that has started can only be changed by a manager."))
    req.status = LeaveRequest.Status.CANCELLED
    req.save(update_fields=["status"])
    audit(user, "leave.cancel", str(req), req)


def balance(user, year: int | None = None) -> dict:
    """Paid leave this year: the allowance, what is approved, what is waiting, and what is left."""
    year = year or timezone.localdate().year
    profile = EmployeeProfile.objects.filter(user=user).first()
    allowance = profile.leave_days if profile else 20
    first, last = date(year, 1, 1), date(year, 12, 31)
    holidays = set(PublicHoliday.objects.filter(date__year=year).values_list("date", flat=True))
    taken = waiting = 0
    for r in LeaveRequest.objects.filter(user=user, kind=LeaveRequest.Kind.ANNUAL, status__in=OPEN_LEAVE, start__lte=last, end__gte=first):
        part = LeaveRequest(start=max(r.start, first), end=min(r.end, last))
        days = part.working_days(holidays)
        if r.status == LeaveRequest.Status.APPROVED:
            taken += days
        else:
            waiting += days
    return {"year": year, "allowance": allowance, "taken": taken, "waiting": waiting, "left": allowance - taken}


def on_leave(start: date, end: date) -> dict[tuple[int, date], LeaveRequest]:
    """Approved leave by (user id, day) for a period."""
    out = {}
    for r in LeaveRequest.objects.filter(status=LeaveRequest.Status.APPROVED, start__lte=end, end__gte=start):
        d = max(r.start, start)
        while d <= min(r.end, end):
            out[(r.user_id, d)] = r
            d = date.fromordinal(d.toordinal() + 1)
    return out


# ---------- Swaps ----------


def ask_swap(shift: ScheduledShift, user, colleague, note: str = "") -> SwapRequest:
    if shift.user_id != user.pk:
        raise BusinessError(_("You can only offer your own shifts."))
    if shift.date < timezone.localdate():
        raise BusinessError(_("That shift is in the past."))
    if colleague is None or colleague.pk == user.pk or not colleague.is_active:
        raise BusinessError(_("Choose a colleague."))
    if SwapRequest.objects.filter(shift=shift, status__in=[SwapRequest.Status.ASKED, SwapRequest.Status.AGREED]).exists():
        raise BusinessError(_("You already asked someone to take this shift."))
    swap = SwapRequest.objects.create(shift=shift, from_user=user, to_user=colleague, note=note.strip()[:200])
    audit(user, "swap.ask", str(swap), shift)
    return swap


@transaction.atomic
def colleague_answer(swap: SwapRequest, user, *, agree: bool) -> SwapRequest:
    swap = SwapRequest.objects.select_for_update().get(pk=swap.pk)
    if swap.to_user_id != user.pk:
        raise BusinessError(_("This request is for someone else."))
    if swap.status != SwapRequest.Status.ASKED:
        raise BusinessError(_("Someone has already answered this request."))
    swap.status = SwapRequest.Status.AGREED if agree else SwapRequest.Status.DECLINED
    swap.save(update_fields=["status"])
    audit(user, "swap.agree" if agree else "swap.refuse", str(swap), swap.shift)
    return swap


@transaction.atomic
def manager_decide(swap: SwapRequest, manager, *, approve: bool) -> SwapRequest:
    swap = SwapRequest.objects.select_for_update().select_related("shift").get(pk=swap.pk)
    if swap.status != SwapRequest.Status.AGREED:
        raise BusinessError(_("Someone has already answered this request."))
    shift = ScheduledShift.objects.select_for_update().get(pk=swap.shift_id)
    if approve:
        if shift.user_id != swap.from_user_id:
            raise BusinessError(_("The shift was changed in the meantime. Decline this request."))
        shift.user = swap.to_user
        shift.save(update_fields=["user"])
    swap.status = SwapRequest.Status.APPROVED if approve else SwapRequest.Status.DECLINED
    swap.decided_by, swap.decided_at = manager, timezone.now()
    swap.save(update_fields=["status", "decided_by", "decided_at"])
    audit(manager, "swap.approve" if approve else "swap.decline", str(swap), shift)
    return swap


def cancel_swap(swap: SwapRequest, user) -> None:
    if swap.from_user_id != user.pk:
        raise BusinessError(_("Only your own requests."))
    if swap.status not in (SwapRequest.Status.ASKED, SwapRequest.Status.AGREED):
        raise BusinessError(_("Someone has already answered this request."))
    swap.status = SwapRequest.Status.CANCELLED
    swap.save(update_fields=["status"])


def waiting_for_managers() -> int:
    return (
        LeaveRequest.objects.filter(status=LeaveRequest.Status.PENDING).count()
        + SwapRequest.objects.filter(status=SwapRequest.Status.AGREED).count()
    )
