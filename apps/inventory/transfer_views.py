from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.accounts.permissions import module_required
from apps.core.exceptions import BusinessError

from . import transfers
from .models import StockItem, StockTransfer
from .views import TABS, _qty


@module_required("inventory")
def transfer_list(request):
    from apps.core.models import GroupMember

    return render(
        request,
        "inventory/transfers.html",
        {"transfers": StockTransfer.objects.select_related("created_by")[:100], "tabs": TABS, "tab": "inventory:transfers",
         "businesses": GroupMember.objects.values_list("name", flat=True)},
    )


@module_required("inventory")
def transfer_send(request):
    items = list(StockItem.objects.filter(is_active=True, on_hand__gt=0).order_by("group", "name"))
    if request.method == "POST":
        quantities = {}
        for i in items:
            v = _qty(request.POST.get(f"q{i.pk}"))
            if v:
                quantities[i.pk] = v
        try:
            t = transfers.send(quantities, to=request.POST.get("to", ""), note=request.POST.get("note", ""), user=request.user)
            messages.success(request, _("Taken out of stock. Give the code below to %(b)s.") % {"b": t.other})
            return redirect("inventory:transfer_detail", pk=t.pk)
        except BusinessError as e:
            messages.error(request, str(e))
    from apps.core.models import GroupMember

    return render(
        request,
        "inventory/transfer_send.html",
        {"items": items, "posted": request.POST, "businesses": GroupMember.objects.values_list("name", flat=True), "tabs": TABS, "tab": "inventory:transfers"},
    )


@module_required("inventory")
def transfer_detail(request, pk):
    t = get_object_or_404(StockTransfer, pk=pk)
    code = transfers.encode(t) if t.direction == StockTransfer.Direction.OUT else ""
    if request.GET.get("download") and code:
        response = HttpResponse(code + "\n", content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="transfer-{t.code}.txt"'
        return response
    lines = [{**ln, "unit_label": transfers.unit_label(ln.get("unit", ""))} for ln in t.lines]
    return render(request, "inventory/transfer_detail.html", {"t": t, "lines": lines, "code": code, "tabs": TABS, "tab": "inventory:transfers"})


@module_required("inventory")
def transfer_receive(request):
    text = request.POST.get("code", "")
    upload = request.FILES.get("file")
    if upload:
        text = upload.read(200_000).decode("utf-8", "replace")
    data = lines = None
    if text:
        try:
            data = transfers.decode(text)
            lines = transfers.preview(data)
            if StockTransfer.objects.filter(code=data["code"], direction=StockTransfer.Direction.IN).exists():
                messages.error(request, _("Transfer %(c)s has already been received.") % {"c": data["code"]})
                data = lines = None
        except BusinessError as e:
            messages.error(request, str(e))
    if data and request.POST.get("confirm"):
        matches = []
        for n in range(len(lines)):
            v = request.POST.get(f"m{n}", "")
            matches.append(int(v) if v.isdigit() else None)
        try:
            t = transfers.receive(data, matches, user=request.user)
            messages.success(request, _("Received into stock: %(n)s lines.") % {"n": len(t.lines)})
            return redirect("inventory:transfer_detail", pk=t.pk)
        except (BusinessError, StockItem.DoesNotExist) as e:
            messages.error(request, str(e) if isinstance(e, BusinessError) else _("Something changed. Paste the code again."))
    return render(
        request,
        "inventory/transfer_receive.html",
        {"data": data, "lines": lines, "code": text if data else "", "stock_items": StockItem.objects.filter(is_active=True).order_by("name"),
         "tabs": TABS, "tab": "inventory:transfers"},
    )
