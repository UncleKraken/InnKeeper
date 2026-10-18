"""
Purchase orders: ask a supplier for what is running low, then receive it as a delivery.

Draft → Ordered (printed, emailed or sent by WhatsApp) → Received (a delivery is recorded and the stock goes up).
"""

import math
from decimal import Decimal
from urllib.parse import quote

from django import forms
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.exceptions import BusinessError
from apps.core.forms import DateInput, StyledFormMixin
from apps.core.models import HotelSettings, audit

from .models import ZERO, PurchaseOrder, PurchaseOrderLine, StockItem, Supplier

WHOLE_UNITS = {"pcs", "bottle", "pack", "box", "portion"}


# ---------- Rules ----------


def suggested_quantity(item: StockItem) -> Decimal:
    """Enough to get back to twice the reorder level (at least the reorder level itself)."""
    need = max(item.min_level * 2 - max(item.on_hand, ZERO), item.min_level)
    if item.unit in WHOLE_UNITS:
        return Decimal(math.ceil(need))
    return need.quantize(Decimal("0.1"), rounding="ROUND_UP")


def on_order_ids() -> set[int]:
    return set(
        PurchaseOrderLine.objects.filter(
            order__status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.SENT]
        ).values_list("stock_item_id", flat=True)
    )


@transaction.atomic
def orders_for_low_stock(user) -> list[PurchaseOrder]:
    """One draft order per supplier with every item at or below its reorder level that isn't already on order."""
    skip = on_order_ids()
    low = [i for i in StockItem.objects.filter(is_active=True, min_level__gt=0).select_related("supplier") if i.is_low and i.pk not in skip]
    if not low:
        return []
    by_supplier: dict = {}
    for item in low:
        by_supplier.setdefault(item.supplier_id, []).append(item)
    created = []
    for supplier_id, items in by_supplier.items():
        po = (
            PurchaseOrder.objects.filter(supplier_id=supplier_id, status=PurchaseOrder.Status.DRAFT).first()
            or PurchaseOrder.objects.create(supplier_id=supplier_id, created_by=user)
        )
        for item in items:
            PurchaseOrderLine.objects.create(order=po, stock_item=item, quantity=suggested_quantity(item), unit_cost=item.cost)
        created.append(po)
        audit(user, "purchase.create", f"{po.number} {po.supplier or ''} ({len(items)})", po)
    return created


def message_text(po: PurchaseOrder) -> str:
    """The order as plain text, for WhatsApp, Viber or an email body."""
    hs = HotelSettings.load()
    lines = [_("Order %(n)s from %(b)s") % {"n": po.number, "b": hs.name}]
    if po.wanted_for:
        lines.append(_("Needed by %(d)s") % {"d": po.wanted_for.strftime("%d.%m.%Y")})
    lines.append("")
    for ln in po.lines.select_related("stock_item"):
        qty = f"{ln.quantity.normalize():f}"
        lines.append(f"• {qty} {ln.stock_item.get_unit_display()} — {ln.stock_item.name}")
    if po.note:
        lines += ["", po.note]
    lines += ["", _("Thank you!"), hs.name]
    if hs.phone:
        lines.append(hs.phone)
    return "\n".join(lines)


def whatsapp_link(po: PurchaseOrder) -> str:
    phone = "".join(ch for ch in (po.supplier.phone if po.supplier else "") if ch.isdigit())
    if phone.startswith("00"):
        phone = phone[2:]
    elif phone.startswith("0") and len(phone) >= 9:
        phone = "355" + phone[1:]  # Albanian mobile written as 069…
    return f"https://wa.me/{phone}?text={quote(message_text(po))}"


def mark_sent(po: PurchaseOrder, user, how: str):
    if po.status == PurchaseOrder.Status.DRAFT:
        if not po.lines.exists():
            raise BusinessError(_("Add at least one item to the order."))
        po.status = PurchaseOrder.Status.SENT
        po.sent_at = timezone.now()
        po.save(update_fields=["status", "sent_at"])
        audit(user, "purchase.sent", f"{po.number} ({how})", po)


# ---------- Views ----------


class OrderHeaderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ["supplier", "wanted_for", "note"]
        widgets = {"wanted_for": DateInput}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)


def _tabs():
    from .views import TABS

    return TABS


@module_required("inventory")
def order_list(request):
    show = request.GET.get("show", "open")
    qs = PurchaseOrder.objects.select_related("supplier").prefetch_related("lines")
    if show == "open":
        qs = qs.filter(status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.SENT])
    skip = on_order_ids()
    low = [i for i in StockItem.objects.filter(is_active=True, min_level__gt=0) if i.is_low]
    return render(
        request,
        "inventory/order_list.html",
        {
            "orders": qs[:200],
            "show": show,
            "low_count": len(low),
            "low_not_ordered": sum(1 for i in low if i.pk not in skip),
            "tabs": _tabs(),
            "tab": "inventory:order_list",
        },
    )


@require_POST
@module_required("inventory")
def order_from_low_stock(request):
    created = orders_for_low_stock(request.user)
    if not created:
        messages.info(request, _("Nothing to order: every item running low is already on an order."))
        return redirect("inventory:order_list")
    if len(created) == 1:
        messages.success(request, _("Order prepared. Check the quantities, then send it."))
        return redirect("inventory:order_detail", pk=created[0].pk)
    messages.success(request, _("%(n)s orders prepared, one per supplier. Check the quantities, then send them.") % {"n": len(created)})
    return redirect("inventory:order_list")


@module_required("inventory")
def order_create(request):
    form = OrderHeaderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        po = form.save(commit=False)
        po.created_by = request.user
        po.save()
        audit(request.user, "purchase.create", f"{po.number} {po.supplier or ''}", po)
        return redirect("inventory:order_detail", pk=po.pk)
    return render(
        request,
        "core/crud_form.html",
        {"form": form, "title": _("Orders to suppliers"), "list_url": reverse("inventory:order_list"), "singular": _("order")},
    )


def _save_lines(po: PurchaseOrder, post) -> None:
    from .views import _qty

    items = {str(i.pk): i for i in StockItem.objects.filter(is_active=True)}
    new = []
    for i, q, c in zip(post.getlist("item"), post.getlist("qty"), post.getlist("cost")):
        if not i:
            continue
        if i not in items:
            raise BusinessError(_("Choose an item from the list."))
        qty = _qty(q)
        if not qty:
            continue
        if qty < 0:
            raise BusinessError(_("Quantities and prices can't be negative."))
        cost = _qty(c) or ZERO
        if cost < 0:
            raise BusinessError(_("Quantities and prices can't be negative."))
        new.append(PurchaseOrderLine(order=po, stock_item=items[i], quantity=qty, unit_cost=cost))
    with transaction.atomic():
        po.lines.all().delete()
        PurchaseOrderLine.objects.bulk_create(new)


@module_required("inventory")
def order_detail(request, pk):
    po = get_object_or_404(PurchaseOrder.objects.select_related("supplier", "delivery", "created_by"), pk=pk)
    editable = po.is_open
    form = OrderHeaderForm(request.POST or None, instance=po) if editable else None
    if request.method == "POST" and editable:
        try:
            if form.is_valid():
                _save_lines(po, request.POST)
                form.save()
                messages.success(request, _("Order saved."))
                return redirect("inventory:order_detail", pk=po.pk)
        except BusinessError as e:
            messages.error(request, str(e))
    lines = list(po.lines.select_related("stock_item"))
    rows = [{"item": str(ln.stock_item_id), "qty": f"{ln.quantity.normalize():f}", "cost": f"{ln.unit_cost.normalize():f}"} for ln in lines]
    rows += [{"item": "", "qty": "", "cost": ""} for _i in range(1 if rows else 3)]
    hs = HotelSettings.load()
    return render(
        request,
        "inventory/order_detail.html",
        {
            "po": po,
            "form": form,
            "lines": lines,
            "rows": rows,
            "items": StockItem.objects.filter(is_active=True),
            "editable": editable,
            "can_email": bool(po.supplier and po.supplier.email and hs.email_configured),
            "whatsapp": whatsapp_link(po) if po.supplier and po.supplier.phone else "",
            "text": message_text(po),
            "tabs": _tabs(),
            "tab": "inventory:order_list",
        },
    )


@module_required("inventory")
def order_print(request, pk):
    po = get_object_or_404(PurchaseOrder.objects.select_related("supplier"), pk=pk)
    return render(request, "inventory/order_print.html", {"po": po, "lines": po.lines.select_related("stock_item")})


@require_POST
@module_required("inventory")
def order_action(request, pk, action):
    po = get_object_or_404(PurchaseOrder.objects.select_related("supplier"), pk=pk)
    try:
        if action == "sent":
            mark_sent(po, request.user, request.POST.get("how", "manual"))
            messages.success(request, _("Marked as ordered."))
        elif action == "email":
            from apps.core import email

            if not (po.supplier and po.supplier.email):
                raise BusinessError(_("Add the supplier's email address first (Suppliers)."))
            if not po.lines.exists():
                raise BusinessError(_("Add at least one item to the order."))
            ok = email.send(
                po.supplier.email,
                _("Order %(n)s from %(b)s") % {"n": po.number, "b": HotelSettings.load().name},
                "inventory/order_email.html",
                {"po": po, "lines": po.lines.select_related("stock_item")},
            )
            if not ok:
                raise BusinessError(_("The email could not be sent. Check Settings → Email."))
            mark_sent(po, request.user, "email")
            messages.success(request, _("Order emailed to %(to)s.") % {"to": po.supplier.email})
        elif action == "cancel":
            if not po.is_open:
                raise BusinessError(_("This order is already closed."))
            po.status = PurchaseOrder.Status.CANCELLED
            po.save(update_fields=["status"])
            audit(request.user, "purchase.cancel", po.number, po)
            messages.success(request, _("Order cancelled."))
        elif action == "receive":
            if not po.is_open:
                raise BusinessError(_("This order is already closed."))
            if not po.lines.exists():
                raise BusinessError(_("Add at least one item to the order."))
            return redirect(f"{reverse('inventory:delivery_create')}?po={po.pk}")
    except BusinessError as e:
        messages.error(request, str(e))
    return redirect("inventory:order_detail", pk=po.pk)


def received(po: PurchaseOrder, delivery, user) -> None:
    """Called when the delivery for this order is saved."""
    po.status = PurchaseOrder.Status.RECEIVED
    po.received_at = timezone.now()
    po.delivery = delivery
    po.save(update_fields=["status", "received_at", "delivery"])
    audit(user, "purchase.received", f"{po.number} → {delivery}", po)
