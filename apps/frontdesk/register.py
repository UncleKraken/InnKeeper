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

from apps.accounts.permissions import module_required
from apps.core.models import SafeCSVWriter, audit

from .models import Reservation

HOME_COUNTRY = {"albania", "shqipëri", "shqiperi", "shqipëria", "shqiperia", "al", "alb", "shqiptar", "shqiptare"}


def is_foreign(nationality: str) -> bool:
    n = (nationality or "").strip().lower()
    return bool(n) and n not in HOME_COUNTRY


def stays(start: date, end: date, *, foreign_only: bool = False):
    """Reservations of guests who were in the property at any time between start and end (inclusive)."""
    qs = (
        Reservation.objects.filter(
            Q(status=Reservation.Status.CHECKED_IN) | Q(status=Reservation.Status.CHECKED_OUT),
            arrival__lte=end,
            departure__gt=start,
        )
        .select_related("guest", "room")
        .order_by("arrival", "room__number")
    )
    rows = list(qs)
    if foreign_only:
        rows = [r for r in rows if is_foreign(r.guest.nationality)]
    return rows


def missing(guest) -> list[str]:
    out = []
    if not guest.document_number:
        out.append(_("document"))
    if not guest.nationality:
        out.append(_("nationality"))
    if not guest.date_of_birth:
        out.append(_("date of birth"))
    return out


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
    rows = [(r, missing(r.guest)) for r in stays(start, end, foreign_only=foreign_only)]
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
                r.room.number,
                r.guest.last_name,
                r.guest.first_name,
                r.guest.nationality,
                r.guest.date_of_birth,
                r.guest.get_document_type_display() if r.guest.document_type else "",
                r.guest.document_number,
                r.guest.address,
                r.arrival,
                r.departure,
                r.adults,
                r.children,
                r.code,
            ]
            for r, _m in rows
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
            "start": start,
            "end": end,
            "foreign_only": foreign_only,
            "incomplete": sum(1 for _r, m in rows if m),
            "people": sum(r.adults + r.children for r, _m in rows),
            "query": request.GET.urlencode(),
        },
    )
