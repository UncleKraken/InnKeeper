"""
Profit per menu item: what each item costs to make (from its recipe, at average purchase price),
what it sells for without VAT, the margin, and how much profit it brought in a period.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import F, Sum
from django.shortcuts import render

from apps.accounts.permissions import module_required
from apps.core.businessday import day_range
from apps.core.models import HotelSettings
from apps.finance.views import _range
from apps.outlets.models import Item, Order, OrderLine

from .models import ZERO, RecipeLine

LOW_MARGIN = Decimal("60")  # food & drink usually aims for 65–75% gross margin


def item_costs() -> dict[int, Decimal]:
    costs: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for rl in RecipeLine.objects.select_related("stock_item"):
        costs[rl.item_id] += rl.quantity * rl.stock_item.cost
    return costs


def rows(start, end) -> list[dict]:
    vat = HotelSettings.load().vat_fraction
    costs = item_costs()
    since, until = day_range(start, end)
    sold = {
        r["item_id"]: r
        for r in OrderLine.objects.filter(
            order__status=Order.Status.CLOSED, order__closed_at__gte=since, order__closed_at__lt=until, item__isnull=False
        )
        .values("item_id")
        .annotate(qty=Sum("quantity"), revenue=Sum(F("quantity") * F("unit_price")))
    }
    out = []
    items = Item.objects.filter(category__outlet__is_active=True).select_related("category__outlet")
    for item in items:
        s = sold.get(item.pk)
        if not item.is_active and not s:
            continue
        has_recipe = item.pk in costs
        cost = costs.get(item.pk, ZERO).quantize(Decimal("0.01"))
        net_price = (item.price * (1 - vat)).quantize(Decimal("0.01"))
        margin = net_price - cost
        pct = (margin * 100 / net_price).quantize(Decimal("1")) if net_price and has_recipe else None
        qty = s["qty"] if s else 0
        revenue_net = ((s["revenue"] or ZERO) * (1 - vat)).quantize(Decimal("0.01")) if s else ZERO
        profit = (revenue_net - cost * qty).quantize(Decimal("0.01")) if has_recipe else None
        out.append(
            {
                "item": item,
                "has_recipe": has_recipe,
                "cost": cost,
                "net_price": net_price,
                "margin": margin,
                "pct": pct,
                "qty": qty,
                "revenue_net": revenue_net,
                "profit": profit,
                "low": pct is not None and pct < LOW_MARGIN,
            }
        )
    return out


@module_required("inventory")
def menu_profit(request):
    from .views import TABS

    start, end = _range(request)
    data = rows(start, end)
    sort = request.GET.get("sort", "profit")
    keys = {
        "profit": lambda r: (r["profit"] is None, -(r["profit"] or 0)),
        "pct": lambda r: (r["pct"] is None, r["pct"] or 0),
        "qty": lambda r: -r["qty"],
        "name": lambda r: r["item"].name.lower(),
    }
    data.sort(key=keys.get(sort, keys["profit"]))
    with_recipe = [r for r in data if r["has_recipe"]]
    revenue = sum((r["revenue_net"] for r in with_recipe), ZERO)
    profit = sum((r["profit"] for r in with_recipe), ZERO)
    if request.GET.get("format") == "xlsx":
        from django.utils.translation import gettext as _

        from apps.core import spreadsheet

        return spreadsheet.response(
            f"menu-profit-{start}-{end}",
            spreadsheet.Sheet(
                _("Profit per item"),
                [_("Item"), _("Outlet"), _("Price without VAT"), _("Cost"), _("Margin"), _("Margin %"), _("Sold"), _("Sales without VAT"), _("Profit")],
                (
                    [r["item"].name, r["item"].category.outlet.name, r["net_price"], r["cost"] if r["has_recipe"] else "",
                     r["margin"] if r["has_recipe"] else "", r["pct"], r["qty"], r["revenue_net"], r["profit"]]
                    for r in data
                ),
                money=(2, 3, 4, 7, 8),
            ),
        )
    return render(
        request,
        "inventory/menu_profit.html",
        {
            "rows": data,
            "start": start,
            "end": end,
            "sort": sort,
            "revenue": revenue,
            "profit": profit,
            "profit_pct": (profit * 100 / revenue).quantize(Decimal("1")) if revenue else None,
            "missing": sum(1 for r in data if not r["has_recipe"]),
            "low_count": sum(1 for r in data if r["low"]),
            "low_margin": LOW_MARGIN,
            "charges_vat": HotelSettings.load().charges_vat,
            "tabs": TABS,
            "tab": "inventory:menu_profit",
        },
    )
