"""
Guest register: who stayed in the property on a given day, with their identity documents,
in the form the police / tourism authorities ask for. Printable and exportable to Excel (.xlsx or CSV).
"""


from datetime import date, timedelta

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.accounts.permissions import module_required
from apps.core.models import SafeCSVWriter, audit

from .models import Reservation

HOME_COUNTRY = {"albania", "shqipëri", "shqiperi", "shqipëria", "shqiperia", "al", "alb", "shqiptar", "shqiptare"}


def is_foreign(nationality: str) -> bool:
    n = (nationality or "").strip().lower()
    return bool(n) and n not in HOME_COUNTRY


def stays(start: date, end: date):
    """Reservations of guests who were in the property at any time between start and end (inclusive)."""
    return list(
        Reservation.objects.filter(
            Q(status=Reservation.Status.CHECKED_IN) | Q(status=Reservation.Status.CHECKED_OUT),
            arrival__lte=end,
            departure__gt=start,
        )
        .select_related("guest", "room")
        .prefetch_related("companions")
        .order_by("arrival", "room__number")
    )


def missing(person, *, child: bool = False) -> list[str]:
    out = []
    if child:
        if not person.date_of_birth:
            out.append(_("date of birth"))
        return out
    if not person.document_number:
        out.append(_("document"))
    if not person.nationality:
        out.append(_("nationality"))
    if not person.date_of_birth:
        out.append(_("date of birth"))
    return out


def people(reservations, *, foreign_only: bool = False) -> list[dict]:
    """One row per person: the main guest, then the others in the room (online check-in or reception)."""
    rows = []
    for r in reservations:
        companions = list(r.companions.all())
        main_missing = missing(r.guest)
        not_entered = max(0, r.adults - 1 - sum(1 for c in companions if not c.is_child))
        if not_entered:
            main_missing.append(ngettext("%(n)s other guest", "%(n)s other guests", not_entered) % {"n": not_entered})
        persons = [{"res": r, "p": r.guest, "main": True, "child": False, "missing": main_missing}]
        persons += [{"res": r, "p": c, "main": False, "child": c.is_child, "missing": missing(c, child=c.is_child)} for c in companions]
        if foreign_only:
            persons = [x for x in persons if is_foreign(x["p"].nationality)]
        rows += persons
    return rows


def _dates(request) -> tuple[date, date]:
    today = timezone.localdate()
    try:
        start = date.fromisoformat(request.GET.get("from", ""))
    except ValueError:
        start = today
    try:
        end = date.fromisoformat(request.GET.get("to", ""))
    except ValueError:
        end = start
    if end < start:
        start, end = end, start
    return start, min(end, start + timedelta(days=92))


@module_required("frontdesk")
def guest_register(request):
    start, end = _dates(request)
    foreign_only = request.GET.get("foreign") == "1"
    reservations = stays(start, end)
    rows = people(reservations, foreign_only=foreign_only)
    fmt = request.GET.get("format")
    if fmt in ("csv", "xlsx"):
        audit(request.user, "register.export", f"{start}–{end} ({len(rows)})")
        header = [
            _("Room"), _("Last name"), _("First name"), _("Nationality"), _("Date of birth"), _("Document type"),
            _("Document number"), _("Address"), _("Arrival"), _("Departure"), _("Adults"), _("Children"),
            _("Reservation"),
        ]
        body = [
            [
                x["res"].room.number,
                x["p"].last_name,
                x["p"].first_name,
                x["p"].nationality,
                x["p"].date_of_birth,
                x["p"].get_document_type_display() if x["p"].document_type else "",
                x["p"].document_number,
                x["p"].address if x["main"] else "",
                x["res"].arrival,
                x["res"].departure,
                x["res"].adults if x["main"] else "",
                x["res"].children if x["main"] else "",
                x["res"].code,
            ]
            for x in rows
        ]
        if fmt == "xlsx":
            from apps.core import spreadsheet

            return spreadsheet.response(f"guest-register-{start}-{end}", spreadsheet.Sheet(_("Guest register"), header, body))
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="guest-register-{start}-{end}.csv"'
        response.write("\ufeff")  # so Excel opens accented names correctly
        w = SafeCSVWriter(response, delimiter=";")
        w.writerow(header)
        for row in body:
            w.writerow([v.strftime("%d.%m.%Y") if isinstance(v, date) else v for v in row])
        return response
    return render(
        request,
        "frontdesk/register.html",
        {
            "rows": rows,
            "stays": len({x["res"].pk for x in rows}),
            "start": start,
            "end": end,
            "foreign_only": foreign_only,
            "incomplete": sum(1 for x in rows if x["missing"]),
            "people": sum(r.adults + r.children for r in reservations),
            "query": request.GET.urlencode(),
        },
    )
