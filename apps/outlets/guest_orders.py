"""
Ordering from the table: each table has its own QR code. Guests open the menu on their phone and send
an order, call the waiter or ask for the bill. Nothing reaches the bill or the kitchen until a member
of staff accepts it, so a prank or a mistake costs nothing.

Guests need no account. Their phone keeps a signed cookie with the requests it sent, so it can show
whether each one was accepted. Requests are limited per phone and per table, and unanswered ones go
stale after an hour.
"""

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.forms import _client_ip
from apps.accounts.permissions import module_enabled, module_required
from apps.core.exceptions import BusinessError
from apps.core.models import audit

from . import services as pos
from .menu import public_link, qr_svg
from .models import GuestRequest, Item, Outlet, Table

COOKIE = "innkeeper_table_requests"
COOKIE_SALT = "innkeeper.table-requests"
STALE_AFTER = timedelta(hours=1)
MAX_PER_PHONE = 12  # requests per phone (IP address) in 10 minutes
MAX_PENDING_PER_TABLE = 5
MAX_LINES = 30
MAX_QUANTITY = 20


def _table_or_404(token: str) -> Table:
    table = (
        Table.objects.select_related("outlet")
        .filter(qr_token=token, is_active=True, outlet__is_active=True, outlet__qr_ordering=True)
        .first()
    )
    if table is None or not token or not module_enabled("outlets"):
        raise Http404
    return table


def fresh(qs):
    return qs.filter(created_at__gte=timezone.now() - STALE_AFTER)


def _my_ids(request) -> list[int]:
    try:
        return [int(x) for x in request.get_signed_cookie(COOKIE, default="", salt=COOKIE_SALT).split(",") if x][-10:]
    except (ValueError, signing.BadSignature):
        return []


def _remember(response, request, pk: int) -> None:
    ids = (_my_ids(request) + [pk])[-10:]
    response.set_signed_cookie(
        COOKIE, ",".join(map(str, ids)), salt=COOKIE_SALT, max_age=6 * 3600, httponly=True, samesite="Lax", secure=request.is_secure()
    )


def _menu(outlet: Outlet, lang: str) -> list[dict]:
    english = lang == "en"
    sections = []
    for cat in outlet.categories.prefetch_related("items__option_groups__options"):
        items = []
        for i in cat.items.all():
            if not i.is_active:
                continue
            groups = [
                {
                    "id": g.pk,
                    "name": g.name_en if english and g.name_en else g.name,
                    "required": g.required,
                    "multiple": g.multiple,
                    "options": [
                        {"id": o.pk, "name": o.name_en if english and o.name_en else o.name, "price": str(o.price_change)}
                        for o in g.options.all()
                        if o.is_active
                    ],
                }
                for g in i.option_groups.all()
            ]
            items.append(
                {
                    "id": i.pk,
                    "name": i.name_en if english and i.name_en else i.name,
                    "description": i.description_en if english and i.description_en else i.description,
                    "price": i.price,
                    "groups": [g for g in groups if g["options"]],
                }
            )
        if items:
            sections.append({"name": cat.name_en if english and cat.name_en else cat.name, "items": items})
    return sections


def _parse_cart(outlet: Outlet, raw: str) -> list[dict]:
    """Check what the phone sent against the menu: only this outlet's available items and valid choices."""
    try:
        cart = json.loads(raw or "[]")
    except ValueError:
        raise BusinessError(_("Something went wrong. Please try again."))
    if not isinstance(cart, list) or not cart:
        raise BusinessError(_("Choose something from the menu first."))
    if len(cart) > MAX_LINES:
        raise BusinessError(_("That is a lot at once. Please ask our staff."))
    items = {i.pk: i for i in Item.objects.filter(category__outlet=outlet, is_active=True).prefetch_related("option_groups__options")}
    lines = []
    for row in cart:
        try:
            item = items[int(row.get("item"))]
            quantity = int(row.get("quantity", 1))
            options = [int(x) for x in row.get("options", [])][:20]
        except (KeyError, TypeError, ValueError, AttributeError):
            raise BusinessError(_("Something on the menu changed. Please reload the page."))
        if not 1 <= quantity <= MAX_QUANTITY:
            raise BusinessError(_("That is a lot at once. Please ask our staff."))
        chosen = pos._chosen_options(item, options)
        price = item.price + sum((o.price_change for o in chosen), Decimal("0"))
        lines.append(
            {
                "item": item.pk,
                "name": item.name,
                "quantity": quantity,
                "options": [o.pk for o in chosen],
                "option_names": ", ".join(o.name for o in chosen),
                "price": str(price),
                "note": str(row.get("note", ""))[:80],
            }
        )
    return lines


def table_page(request, token):
    table = _table_or_404(token)
    outlet = table.outlet
    lang = request.GET.get("lang") or translation.get_language() or "sq"
    lang = "en" if lang.startswith("en") else "sq"
    translation.activate(lang)
    error = ""
    if request.method == "POST":
        try:
            req = _create(request, table)
        except BusinessError as e:
            error = str(e)
        else:
            response = redirect(f"{request.path}?lang={lang}&sent={req.kind}")
            _remember(response, request, req.pk)
            return response
    mine = list(GuestRequest.objects.filter(pk__in=_my_ids(request), table=table).order_by("-created_at")[:5])
    sections = _menu(outlet, lang)
    return render(
        request,
        "outlets/table_order.html",
        {
            "table": table,
            "outlet": outlet,
            "sections": sections,
            "catalog": {str(i["id"]): {"name": i["name"], "price": str(i["price"]), "groups": i["groups"]} for s in sections for i in s["items"]},
            "lang": lang,
            "error": error,
            "sent": request.GET.get("sent", ""),
            "mine": mine,
            "stale_before": timezone.now() - STALE_AFTER,
        },
    )


def _create(request, table: Table) -> GuestRequest:
    kind = request.POST.get("kind", GuestRequest.Kind.ORDER)
    if kind not in GuestRequest.Kind.values:
        raise BusinessError(_("Something went wrong. Please try again."))
    key = f"innkeeper:table-req:{_client_ip(request)}"
    if cache.get(key, 0) >= MAX_PER_PHONE:
        raise BusinessError(_("Too many requests from this phone. Please ask our staff."))
    pending = fresh(GuestRequest.objects.filter(table=table, status=GuestRequest.Status.PENDING))
    if kind != GuestRequest.Kind.ORDER:
        same = pending.filter(kind=kind).first()
        if same:
            return same  # already asked: don't call the waiter twice
    elif pending.filter(kind=GuestRequest.Kind.ORDER).count() >= MAX_PENDING_PER_TABLE:
        raise BusinessError(_("Your orders are waiting for our staff. Please wait a moment."))
    lines = _parse_cart(table.outlet, request.POST.get("cart", "")) if kind == GuestRequest.Kind.ORDER else []
    req = GuestRequest.objects.create(
        outlet=table.outlet, table=table, kind=kind, lines=lines, note=request.POST.get("note", "").strip()[:200]
    )
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, 600)
    return req


def table_status(request, token):
    table = _table_or_404(token)
    mine = GuestRequest.objects.filter(pk__in=_my_ids(request), table=table)
    return JsonResponse({"requests": {str(r.pk): r.status for r in mine}})


# ---------- Staff ----------


def pending_for(user):
    qs = fresh(GuestRequest.objects.filter(status=GuestRequest.Status.PENDING)).select_related("table", "outlet")
    return [r for r in qs if r.outlet.user_can_use(user)]


@module_required("outlets")
def requests_page(request):
    pending = pending_for(request.user)
    recent = (
        GuestRequest.objects.exclude(status=GuestRequest.Status.PENDING)
        .filter(handled_at__gte=timezone.now() - timedelta(hours=3))
        .select_related("table", "outlet", "handled_by")
        .order_by("-handled_at")[:15]
    )
    return render(request, "outlets/guest_requests.html", {"pending": pending, "recent": recent})


@module_required("outlets")
def requests_count(request):
    pending = pending_for(request.user)
    return JsonResponse({"count": len(pending), "latest": max((r.pk for r in pending), default=0)})


def _pending_or_404(request, pk) -> GuestRequest:
    req = get_object_or_404(GuestRequest.objects.select_for_update().select_related("table", "outlet"), pk=pk)
    if not req.outlet.user_can_use(request.user):
        raise Http404
    if req.status != GuestRequest.Status.PENDING:
        raise BusinessError(_("Someone has already answered this request."))
    return req


@require_POST
@module_required("outlets")
def accept(request, pk):
    try:
        with transaction.atomic():
            req = _pending_or_404(request, pk)
            order = accept_request(req, request.user)
    except BusinessError as e:
        messages.error(request, str(e))
        return redirect("outlets:guest_requests")
    if order is not None:
        messages.success(request, _("Table %(t)s: the order is on the bill and sent to the kitchen.") % {"t": req.table})
        return redirect("outlets:order", pk=order.pk)
    messages.success(request, _("Done."))
    return redirect("outlets:guest_requests")


def accept_request(req: GuestRequest, user):
    """Put a guest's order on the table's bill and send it to the kitchen (or mark a call as done)."""
    now = timezone.now()
    if req.kind != GuestRequest.Kind.ORDER:
        req.status, req.handled_by, req.handled_at = GuestRequest.Status.DONE, user, now
        req.save(update_fields=["status", "handled_by", "handled_at"])
        audit(user, "guest_request.done", f"{req.table} · {req.get_kind_display()}", req.table)
        return None
    order = req.table.open_order() or pos.open_order(req.outlet, user=user, table=req.table)
    added, skipped = 0, []
    for line in req.lines:
        item = Item.objects.filter(pk=line.get("item")).first()
        try:
            if item is None:
                raise BusinessError("")
            pos.add_item(order, item, user=user, quantity=int(line["quantity"]), note=line.get("note", ""), option_ids=line.get("options", []))
            added += 1
        except BusinessError:
            skipped.append(line.get("name", "?"))
    if not added:
        raise BusinessError(_("None of these items is available any more. Decline the order and tell the guest."))
    if req.note:
        order.note = (f"{order.note} · " if order.note else "") + f"QR: {req.note}"
        order.note = order.note[:255]
        order.save(update_fields=["note"])
    pos.send_to_kitchen(order, user=user)
    req.status, req.handled_by, req.handled_at, req.order = GuestRequest.Status.ACCEPTED, user, now, order
    if skipped:
        req.reason = (_("Not available: %(items)s") % {"items": ", ".join(skipped)})[:120]
    req.save(update_fields=["status", "handled_by", "handled_at", "order", "reason"])
    audit(user, "guest_request.accept", f"{req.table}: {req.item_count} · #{order.number}", order)
    return order


@require_POST
@module_required("outlets")
def decline(request, pk):
    try:
        with transaction.atomic():
            req = _pending_or_404(request, pk)
            req.status, req.handled_by, req.handled_at = GuestRequest.Status.DECLINED, request.user, timezone.now()
            req.reason = request.POST.get("reason", "").strip()[:120]
            req.save(update_fields=["status", "handled_by", "handled_at", "reason"])
            audit(request.user, "guest_request.decline", f"{req.table} · {req.reason}", req.table)
    except BusinessError as e:
        messages.error(request, str(e))
    return redirect("outlets:guest_requests")


@module_required("management")
def table_qr_cards(request, pk):
    outlet = get_object_or_404(Outlet, pk=pk)
    cards = []
    for t in outlet.tables.filter(is_active=True):
        if not t.qr_token:
            t.save()
        url = public_link(request, reverse("menu:table", args=[t.qr_token]))
        cards.append({"table": t, "url": url, "qr": qr_svg(url)})
    host = cards[0]["url"].split("//", 1)[-1].split("/")[0].split(":")[0] if cards else ""
    return render(
        request,
        "outlets/table_qr_cards.html",
        {"outlet": outlet, "cards": cards, "local_only": host in {"localhost", "127.0.0.1", "0.0.0.0"}},
    )


@require_POST
@module_required("management")
def new_table_codes(request, pk):
    """New QR codes for every table of an outlet (e.g. a printed card was stolen). Old cards stop working."""
    outlet = get_object_or_404(Outlet, pk=pk)
    for t in outlet.tables.all():
        t.qr_token = ""
        t.save()
    audit(request.user, "outlet.table_codes", outlet.name, outlet)
    messages.success(request, _("New table codes created. Print the new cards."))
    return redirect("outlets:table_qr_cards", pk=pk)
