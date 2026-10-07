"""
Guest register: who stayed in the property on a given day, with their identity documents,
in the form the police / tourism authorities ask for. Printable and exportable to Excel (CSV).
"""

import csv
from datetime import date, timedelta

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.permissions import module_required
from apps.core.models import audit

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
    if request.GET.get("format") == "csv":
        audit(request.user, "register.export", f"{start}–{end} ({len(rows)})")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="guest-register-{start}-{end}.csv"'
        response.write("﻿")  # so Excel opens accented names correctly
        w = csv.writer(response, delimiter=";")
        w.writerow(
            [
                _("Room"),
                _("Last name"),
                _("First name"),
                _("Nationality"),
                _("Date of birth"),
                _("Document type"),
                _("Document number"),
                _("Address"),
                _("Arrival"),
                _("Departure"),
                _("Adults"),
                _("Children"),
                _("Reservation"),
            ]
        )
        for r, _m in rows:
            g = r.guest
            w.writerow(
                [
                    r.room.number,
                    g.last_name,
                    g.first_name,
                    g.nationality,
                    g.date_of_birth.strftime("%d.%m.%Y") if g.date_of_birth else "",
                    g.get_document_type_display() if g.document_type else "",
                    g.document_number,
                    g.address,
                    r.arrival.strftime("%d.%m.%Y"),
                    r.departure.strftime("%d.%m.%Y"),
                    r.adults,
                    r.children,
                    r.code,
                ]
            )
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
