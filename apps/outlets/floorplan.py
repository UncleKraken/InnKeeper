"""Floor plan editor: drag tables into place, rename, renumber, resize and group them into areas."""

import json

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.models import audit

from .models import Order, Outlet, Table

PLAN_W, PLAN_H = 1000, 640
MIN_SIZE, MAX_SIZE = 40, 400


def table_payload(t: Table) -> dict:
    return {
        "id": t.pk,
        "name": t.name,
        "seats": t.seats,
        "shape": t.shape,
        "zone": t.zone,
        "x": t.pos_x,
        "y": t.pos_y,
        "w": t.width,
        "h": t.height,
        "active": t.is_active,
    }


@module_required("management")
def floor_plan(request, pk):
    outlet = get_object_or_404(Outlet, pk=pk)
    tables = [table_payload(t) for t in outlet.tables.all()]
    busy = list(outlet.orders.filter(status=Order.Status.OPEN, table__isnull=False).values_list("table_id", flat=True))
    return render(
        request,
        "outlets/floor_plan.html",
        {
            "outlet": outlet,
            "outlets": Outlet.objects.filter(uses_tables=True),
            "plan": {"tables": tables, "busy": busy, "w": PLAN_W, "h": PLAN_H},
            "shapes": Table.Shape.choices,
        },
    )


def _clamp(value, low, high) -> int:
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return low


@require_POST
@module_required("management")
def floor_plan_save(request, pk):
    outlet = get_object_or_404(Outlet, pk=pk)
    try:
        data = json.loads(request.body.decode("utf-8"))
        rows = data["tables"]
        assert isinstance(rows, list)
    except (ValueError, KeyError, AssertionError):
        return JsonResponse({"ok": False, "error": _("The plan could not be read.")}, status=400)

    names = [str(r.get("name", "")).strip()[:30] for r in rows]
    if any(not n for n in names):
        return JsonResponse({"ok": False, "error": _("Every table needs a name or number.")}, status=400)
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        return JsonResponse(
            {"ok": False, "error": _("These names are used twice: %(names)s") % {"names": ", ".join(duplicates)}},
            status=400,
        )

    existing = {t.pk: t for t in outlet.tables.all()}
    keep_ids = {int(r["id"]) for r in rows if r.get("id") and int(r["id"]) in existing}
    busy = set(outlet.orders.filter(status=Order.Status.OPEN, table__isnull=False).values_list("table_id", flat=True))
    to_delete = [t for pk_, t in existing.items() if pk_ not in keep_ids]
    blocked = [t.name for t in to_delete if t.pk in busy]
    if blocked:
        return JsonResponse(
            {"ok": False, "error": _("Close the open orders first: table %(names)s") % {"names": ", ".join(blocked)}},
            status=400,
        )

    with transaction.atomic():
        for t in to_delete:
            # Keep old receipts readable after the table is gone.
            t.orders.filter(label="").update(label=_("Table %(name)s") % {"name": t.name})
            t.delete()
        # Free all names first so swapping "1" and "2" doesn't hit the unique constraint.
        for pk_ in keep_ids:
            Table.objects.filter(pk=pk_).update(name=f"__tmp_{pk_}")
        for order, (r, name) in enumerate(zip(rows, names), start=1):
            t = existing.get(int(r["id"])) if r.get("id") and int(r["id"]) in keep_ids else Table(outlet=outlet)
            t.name = name
            t.seats = _clamp(r.get("seats", 4), 1, 99)
            t.shape = r.get("shape") if r.get("shape") in Table.Shape.values else Table.Shape.SQUARE
            t.zone = str(r.get("zone", "")).strip()[:40]
            t.width = _clamp(r.get("w", 90), MIN_SIZE, MAX_SIZE)
            t.height = _clamp(r.get("h", 90), MIN_SIZE, MAX_SIZE)
            t.pos_x = _clamp(r.get("x", 0), 0, PLAN_W - t.width)
            t.pos_y = _clamp(r.get("y", 0), 0, PLAN_H - t.height)
            t.is_active = bool(r.get("active", True))
            t.sort_order = order
            t.save()
    audit(request.user, "floorplan.save", f"{outlet}: {len(rows)} tables", outlet)
    messages.success(request, _("Floor plan saved."))
    return JsonResponse({"ok": True, "tables": [table_payload(t) for t in outlet.tables.all()]})
