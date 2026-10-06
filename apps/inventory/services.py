"""Stock rules. Every change to a quantity goes through `_move` so the history always adds up."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings, audit

from .models import ZERO, Delivery, RecipeLine, StockCount, StockItem, StockMove, Supplier

CENT = Decimal("0.01")


def tracking_enabled() -> bool:
    return HotelSettings.load().module_inventory


def _move(stock_item: StockItem, kind: str, quantity: Decimal, *, user=None, unit_cost=None, **links) -> StockMove:
    item = StockItem.objects.select_for_update().get(pk=stock_item.pk)
    item.on_hand += quantity
    item.save(update_fields=["on_hand"])
    return StockMove.objects.create(
        stock_item=item,
        kind=kind,
        quantity=quantity,
        unit_cost=item.cost if unit_cost is None else unit_cost,
        balance=item.on_hand,
        created_by=user if getattr(user, "is_authenticated", False) else None,
        **links,
    )


# ---------- Sales ----------


def consume_for_order(order, user=None) -> int:
    """Take the ingredients of a closed bill out of stock. Safe to call twice."""
    if not tracking_enabled() or order.stock_moves.filter(kind=StockMove.Kind.SALE).exists():
        return 0
    needed: dict[int, Decimal] = {}
    lines = order.active_lines.exclude(item__isnull=True)
    recipes = RecipeLine.objects.filter(item_id__in=lines.values("item_id")).select_related("stock_item")
    by_item: dict[int, list[RecipeLine]] = {}
    for r in recipes:
        by_item.setdefault(r.item_id, []).append(r)
    for line in lines:
        for r in by_item.get(line.item_id, []):
            needed[r.stock_item_id] = needed.get(r.stock_item_id, ZERO) + r.quantity * line.quantity
    for stock_id, qty in needed.items():
        _move(
            StockItem(pk=stock_id),
            StockMove.Kind.SALE,
            -qty,
            user=user,
            order=order,
            business_date=timezone.localdate(),
            note=f"{order.outlet} #{order.number}",
        )
    return len(needed)


def return_for_order(order, user=None) -> int:
    """A voided bill puts its ingredients back (they were not really used up, or it was a mistake)."""
    sold = order.stock_moves.filter(kind=StockMove.Kind.SALE).values("stock_item").annotate(q=Sum("quantity"))
    returned = order.stock_moves.filter(kind=StockMove.Kind.RETURN).exists()
    if returned:
        return 0
    for row in sold:
        _move(
            StockItem(pk=row["stock_item"]),
            StockMove.Kind.RETURN,
            -row["q"],
            user=user,
            order=order,
            note=f"{order.outlet} #{order.number}",
        )
    return len(sold)


# ---------- Deliveries ----------


@dataclass
class DeliveryLine:
    stock_item: StockItem
    quantity: Decimal
    unit_cost: Decimal


@transaction.atomic
def receive_delivery(
    lines: list[DeliveryLine],
    *,
    user,
    supplier: Supplier | None = None,
    business_date: date | None = None,
    reference: str = "",
    note: str = "",
    record_expense: bool = False,
    paid_with: str = "cash",
) -> Delivery:
    lines = [ln for ln in lines if ln.quantity]
    if not lines:
        raise BusinessError(_("Add at least one item to the delivery."))
    if any(ln.quantity < 0 or ln.unit_cost < 0 for ln in lines):
        raise BusinessError(_("Quantities and prices can't be negative."))
    business_date = business_date or timezone.localdate()
    delivery = Delivery.objects.create(
        supplier=supplier, business_date=business_date, reference=reference, note=note, created_by=user
    )
    total = ZERO
    for ln in lines:
        item = StockItem.objects.select_for_update().get(pk=ln.stock_item.pk)
        # Average purchase price: what's on the shelf is worth the old price, the new goods the new price.
        old = max(item.on_hand, ZERO)
        if old + ln.quantity > 0:
            item.cost = (old * item.cost + ln.quantity * ln.unit_cost) / (old + ln.quantity)
        if supplier and not item.supplier_id:
            item.supplier = supplier
        item.save(update_fields=["cost", "supplier"])
        _move(
            item,
            StockMove.Kind.DELIVERY,
            ln.quantity,
            user=user,
            unit_cost=ln.unit_cost,
            delivery=delivery,
            business_date=business_date,
            note=str(supplier or ""),
        )
        total += ln.quantity * ln.unit_cost
    delivery.total = total.quantize(CENT)
    if record_expense and delivery.total > 0:
        from apps.finance.models import Expense

        delivery.expense = Expense.objects.create(
            business_date=business_date,
            category=Expense.Category.FOOD_DRINK,
            description=_("Delivery") + (f" – {supplier}" if supplier else ""),
            supplier=supplier.name if supplier else "",
            amount=delivery.total,
            method=paid_with,
            reference=reference,
            created_by=user,
        )
    delivery.save(update_fields=["total", "expense"])
    audit(user, "stock.delivery", f"{delivery} {delivery.total}", delivery)
    return delivery


# ---------- Waste, counts, adjustments ----------


@transaction.atomic
def record_waste(stock_item: StockItem, quantity: Decimal, *, user, reason: str) -> StockMove:
    if quantity <= 0:
        raise BusinessError(_("Enter how much was wasted."))
    if not reason.strip():
        raise BusinessError(_("Say what happened (e.g. broken bottle, expired)."))
    move = _move(stock_item, StockMove.Kind.WASTE, -quantity, user=user, note=reason.strip()[:255])
    audit(user, "stock.waste", f"{stock_item} -{quantity}: {reason}", stock_item)
    return move


@transaction.atomic
def apply_count(counted: dict[int, Decimal], *, user, note: str = "", business_date: date | None = None) -> StockCount:
    """Set stock to what was physically counted. Items left blank are not changed."""
    if not counted:
        raise BusinessError(_("Enter at least one counted quantity."))
    count = StockCount.objects.create(business_date=business_date or timezone.localdate(), note=note, created_by=user)
    diff_value = ZERO
    for item in StockItem.objects.select_for_update().filter(pk__in=counted):
        new = counted[item.pk]
        if new < 0:
            raise BusinessError(_("Counted quantities can't be negative."))
        diff = new - item.on_hand
        if diff:
            _move(item, StockMove.Kind.COUNT, diff, user=user, count=count, business_date=count.business_date)
            diff_value += diff * item.cost
    count.difference_value = diff_value.quantize(CENT)
    count.save(update_fields=["difference_value"])
    audit(user, "stock.count", f"{count} {count.difference_value}", count)
    return count


# ---------- Reports ----------


def usage(start: date, end: date):
    """Per stock item: used by sales, wasted, received and corrected by counts in the period, with value."""
    rows = (
        StockMove.objects.filter(business_date__range=(start, end))
        .values("stock_item", "kind")
        .annotate(q=Sum("quantity"))
    )
    out: dict[int, dict] = {}
    for r in rows:
        d = out.setdefault(
            r["stock_item"],
            {"sale": ZERO, "return": ZERO, "waste": ZERO, "delivery": ZERO, "count": ZERO, "adjust": ZERO},
        )
        d[r["kind"]] += r["q"]
    items = {i.pk: i for i in StockItem.objects.filter(pk__in=out)}
    result = []
    for pk, d in out.items():
        item = items[pk]
        used = -(d["sale"] + d["return"])
        result.append(
            {
                "item": item,
                "used": used,
                "used_value": (used * item.cost).quantize(CENT),
                "wasted": -d["waste"],
                "wasted_value": (-d["waste"] * item.cost).quantize(CENT),
                "received": d["delivery"],
                "counted": d["count"],
                "counted_value": (d["count"] * item.cost).quantize(CENT),
            }
        )
    result.sort(key=lambda r: -r["used_value"])
    return result


def recipe_cost(menu_item) -> Decimal:
    return sum((r.quantity * r.stock_item.cost for r in menu_item.recipe.select_related("stock_item")), ZERO).quantize(
        CENT
    )
