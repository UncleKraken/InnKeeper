from datetime import date, time, timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.accounts.permissions import module_required
from apps.core.crud import CrudCreateView, CrudListView, CrudUpdateView
from apps.core.exceptions import BusinessError
from apps.core.forms import DateInput, StyledFormMixin
from apps.core.models import audit

from . import services
from .models import EmployeeProfile, Position, ScheduledShift, TimeEntry

TABS = [
    ("staff:attendance", gettext_lazy("Attendance")),
    ("staff:schedule", gettext_lazy("Schedule")),
    ("accounts:staff_list", gettext_lazy("Staff")),
    ("staff:position_list", gettext_lazy("Positions")),
]


def team():
    """People who work here."""
    return User.objects.filter(is_active=True).order_by("first_name", "username")


def _back(request, default="/"):
    nxt = request.POST.get("next") or request.META.get("HTTP_REFERER") or default
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        nxt = default
    return redirect(nxt)


# ---------- Clocking in and out ----------


@require_POST
@login_required
def clock(request):
    try:
        direction, entry = services.toggle(request.user)
        if direction == "in":
            messages.success(request, _("Clocked in at %(t)s. Have a good shift!") % {"t": timezone.localtime(entry.clock_in).strftime("%H:%M")})
        else:
            messages.success(
                request,
                _("Clocked out at %(t)s: %(h)s hours.") % {"t": timezone.localtime(entry.clock_out).strftime("%H:%M"), "h": entry.hours},
            )
    except BusinessError as e:
        messages.error(request, str(e))
    return _back(request)


@login_required
def my_hours(request):
    today = timezone.localdate()
    first = today.replace(day=1)
    entries = TimeEntry.objects.filter(user=request.user, clock_in__date__gte=first).order_by("-clock_in")
    upcoming = ScheduledShift.objects.filter(user=request.user, date__gte=today).select_related("position")[:14]
    return render(
        request,
        "staff/my_hours.html",
        {
            "entries": entries,
            "upcoming": upcoming,
            "open": services.open_entry(request.user),
            "month_hours": sum((e.hours for e in entries if e.clock_out), 0),
        },
    )


# ---------- Attendance (managers) ----------


def _range(request):
    from apps.finance.views import _range as finance_range

    return finance_range(request)


@module_required("management")
def attendance(request):
    start, end = _range(request)
    if "from" not in request.GET:
        end = timezone.localdate()
        start = end.replace(day=1)
    rows = services.attendance(start, end)
    if request.GET.get("format") == "xlsx":
        return _attendance_xlsx(rows, start, end)
    return render(
        request,
        "staff/attendance.html",
        {"rows": rows, "start": start, "end": end, "now": services.working_now(), "today": timezone.localdate(), "tabs": TABS, "tab": "staff:attendance"},
    )


def _attendance_xlsx(rows, start, end):
    from apps.core import spreadsheet

    summary = spreadsheet.Sheet(
        _("Summary"),
        [_("Name"), _("Position"), _("Days worked"), _("Hours worked"), _("Hours planned"), _("Difference"), _("Late"), _("Did not come"), _("Missing clock-out")],
        (
            [str(r["user"]), str(getattr(getattr(r["user"], "employee", None), "position", "") or ""), r["days"], r["worked"], r["planned"],
             r["difference"], r["late"], r["no_show"], r["missing_out"]]
            for r in rows
        ),
    )
    entries = spreadsheet.Sheet(
        _("Clock-ins"),
        [_("Name"), _("Date"), _("Clock in"), _("Clock out"), _("Break (minutes)"), _("Hours"), _("Note")],
        (
            [str(r["user"]), timezone.localtime(e.clock_in).date(), timezone.localtime(e.clock_in).strftime("%H:%M"),
             timezone.localtime(e.clock_out).strftime("%H:%M") if e.clock_out else "", e.break_minutes,
             e.hours if e.clock_out else "", (e.note + (" · " + e.edit_reason if e.edit_reason else "")).strip(" ·")]
            for r in rows
            for e in r["entries"]
        ),
    )
    return spreadsheet.response(f"attendance-{start}-{end}", summary, entries)


@module_required("management")
def person_hours(request, pk):
    person = get_object_or_404(User, pk=pk)
    start, end = _range(request)
    if "from" not in request.GET:
        end = timezone.localdate()
        start = end.replace(day=1)
    rows = services.attendance(start, end, users=[person])
    row = rows[0] if rows else {"entries": [], "shifts": [], "worked": 0, "planned": 0, "difference": None, "late": 0, "no_show": 0, "missing_out": 0, "days": 0}
    return render(
        request,
        "staff/person_hours.html",
        {"person": person, "row": row, "start": start, "end": end, "open": services.open_entry(person), "tabs": TABS, "tab": "staff:attendance"},
    )


class EntryForm(StyledFormMixin, forms.ModelForm):
    clock_in = forms.DateTimeField(label=gettext_lazy("Clock in"), widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"))
    clock_out = forms.DateTimeField(
        label=gettext_lazy("Clock out"), required=False, widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
    )
    edit_reason = forms.CharField(label=gettext_lazy("Reason for the change"), max_length=200, help_text=gettext_lazy("Kept in the activity log, e.g. “forgot to clock out”."))

    class Meta:
        model = TimeEntry
        fields = ["clock_in", "clock_out", "break_minutes", "note", "edit_reason"]

    def clean(self):
        cleaned = super().clean()
        a, b = cleaned.get("clock_in"), cleaned.get("clock_out")
        if a and b and b <= a:
            self.add_error("clock_out", _("Clock out must be after clock in."))
        if a and b and b - a > timedelta(hours=24):
            self.add_error("clock_out", _("A shift can't be longer than 24 hours."))
        return cleaned


@module_required("management")
def entry_edit(request, pk=None, user_pk=None):
    entry = get_object_or_404(TimeEntry, pk=pk) if pk else TimeEntry(user=get_object_or_404(User, pk=user_pk), source=TimeEntry.Source.MANUAL)
    form = EntryForm(request.POST or None, instance=entry, initial={"edit_reason": ""} if pk else {"clock_in": timezone.localtime().replace(second=0, microsecond=0)})
    if request.method == "POST":
        if request.POST.get("delete") == "1" and pk:
            reason = request.POST.get("edit_reason", "").strip()
            if not reason:
                messages.error(request, _("Give a reason."))
            else:
                audit(request.user, "staff.entry_delete", f"{entry} – {reason}", entry)
                user_id = entry.user_id
                entry.delete()
                messages.success(request, _("Deleted."))
                return redirect("staff:person_hours", pk=user_id)
        elif form.is_valid():
            e = form.save(commit=False)
            e.edited_by = request.user
            if not e.position_id:
                e.position = services._position(e.user)
            try:
                e.save()
            except Exception:
                form.add_error("clock_out", _("This person is already clocked in: add the clock-out time."))
            else:
                audit(request.user, "staff.entry_edit", f"{e} – {e.edit_reason}", e)
                messages.success(request, _("Saved."))
                return redirect("staff:person_hours", pk=e.user_id)
    return render(request, "staff/entry_form.html", {"form": form, "entry": entry, "person": entry.user, "tabs": TABS, "tab": "staff:attendance"})


@require_POST
@module_required("management")
def clock_for(request, pk):
    """A manager clocks someone in or out (e.g. a cleaner who has no device)."""
    person = get_object_or_404(User, pk=pk)
    try:
        direction, _entry = services.toggle(person, source=TimeEntry.Source.MANUAL)
        audit(request.user, f"staff.clock_{direction}_for", str(person), person)
        messages.success(request, _("%(name)s clocked in.") % {"name": person} if direction == "in" else _("%(name)s clocked out.") % {"name": person})
    except BusinessError as e:
        messages.error(request, str(e))
    return _back(request, reverse("staff:attendance"))


# ---------- Schedule ----------


def _week_start(value: str) -> date:
    try:
        d = date.fromisoformat(value)
    except ValueError:
        d = timezone.localdate()
    return d - timedelta(days=d.weekday())


@module_required("management")
def schedule(request):
    week = _week_start(request.GET.get("week", ""))
    days = [week + timedelta(days=i) for i in range(7)]
    people = list(team().select_related("employee__position"))
    shifts = ScheduledShift.objects.filter(date__range=(days[0], days[-1])).select_related("position")
    grid = {(s.user_id, s.date): [] for s in shifts}
    for s in shifts:
        grid[(s.user_id, s.date)].append(s)
    rows = []
    for p in people:
        cells = [grid.get((p.pk, d), []) for d in days]
        hours = sum((s.hours for c in cells for s in c), 0)
        rows.append({"person": p, "cells": list(zip(days, cells, strict=True)), "hours": hours})
    return render(
        request,
        "staff/schedule.html",
        {
            "days": days,
            "rows": rows,
            "week": week,
            "prev": week - timedelta(days=7),
            "next": week + timedelta(days=7),
            "today": timezone.localdate(),
            "print_mode": request.GET.get("print") == "1",
            "tabs": TABS,
            "tab": "staff:schedule",
        },
    )


class ShiftForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ScheduledShift
        fields = ["user", "date", "start", "end", "position", "note"]
        widgets = {
            "date": DateInput(),
            "start": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }
        labels = {"user": gettext_lazy("Who")}
        help_texts = {"end": gettext_lazy("Earlier than the start means it ends the next day (e.g. 18:00–02:00).")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = team()
        self.fields["position"].queryset = Position.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start") and cleaned.get("start") == cleaned.get("end"):
            self.add_error("end", _("Start and end can't be the same."))
        return cleaned


@module_required("management")
def shift_form(request, pk=None):
    shift = get_object_or_404(ScheduledShift, pk=pk) if pk else None
    initial = {}
    if not shift:
        initial = {"date": request.GET.get("date") or timezone.localdate(), "user": request.GET.get("user"), "start": time(8), "end": time(16)}
        person = User.objects.filter(pk=request.GET.get("user") or 0).select_related("employee__position").first()
        if person and getattr(person, "employee", None) and person.employee.position_id:
            initial["position"] = person.employee.position_id
    form = ShiftForm(request.POST or None, instance=shift, initial=initial)
    week = None
    if request.method == "POST":
        if request.POST.get("delete") == "1" and shift:
            week = _week_start(shift.date.isoformat())
            audit(request.user, "staff.shift_delete", str(shift))
            shift.delete()
            return redirect(f"{reverse('staff:schedule')}?week={week.isoformat()}")
        if form.is_valid():
            s = form.save()
            audit(request.user, "staff.shift", str(s), s)
            week = _week_start(s.date.isoformat())
            return redirect(f"{reverse('staff:schedule')}?week={week.isoformat()}")
    return render(request, "staff/shift_form.html", {"form": form, "shift": shift, "tabs": TABS, "tab": "staff:schedule"})


@require_POST
@module_required("management")
def copy_week(request):
    week = _week_start(request.POST.get("week", ""))
    n = services.copy_week(week, request.user)
    messages.success(request, _("%(n)s shifts copied from last week.") % {"n": n} if n else _("Nothing to copy: last week is empty or this week is already planned."))
    return redirect(f"{reverse('staff:schedule')}?week={week.isoformat()}")


# ---------- Employee details and positions ----------


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = EmployeeProfile
        exclude = ["user"]
        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
            "date_of_birth": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3, "data-full": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["position"].queryset = Position.objects.filter(is_active=True)


@module_required("management")
def profile(request, pk):
    person = get_object_or_404(User, pk=pk)
    instance = EmployeeProfile.objects.filter(user=person).first() or EmployeeProfile(user=person)
    form = ProfileForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit(request.user, "staff.profile", str(person), person)  # what changed is not logged: it's personal data
        messages.success(request, _("Saved."))
        return redirect("accounts:staff_edit", pk=person.pk)
    return render(request, "staff/profile_form.html", {"form": form, "person": person})


class PositionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Position
        fields = ["name", "color", "sort_order", "is_active"]


class PositionList(CrudListView):
    model = Position
    title = gettext_lazy("Positions")
    singular = gettext_lazy("position")
    list_url_name = "staff:position_list"
    create_url_name = "staff:position_create"
    update_url_name = "staff:position_edit"
    tabs = TABS
    columns = [("name", gettext_lazy("Name"), "text"), ("color", gettext_lazy("Colour"), "choice"), ("is_active", gettext_lazy("Active"), "bool")]


class PositionCreate(CrudCreateView):
    model = Position
    form_class = PositionForm
    title = gettext_lazy("Positions")
    singular = gettext_lazy("position")
    list_url_name = "staff:position_list"


class PositionEdit(CrudUpdateView):
    model = Position
    form_class = PositionForm
    title = gettext_lazy("Positions")
    singular = gettext_lazy("position")
    list_url_name = "staff:position_list"

