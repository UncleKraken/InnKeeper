"""Prices at the moment of the sale: time-based rules (happy hour, late-night prices)."""

from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from .models import Item, PriceRule

CENT = Decimal("0.01")


def rule_for(item: Item, when=None) -> PriceRule | None:
    """The time-based price that applies to this item now (the first that matches)."""
    when = timezone.localtime(when or timezone.now())
    category = item.category
    for rule in PriceRule.objects.filter(is_active=True).prefetch_related("outlets", "categories"):
        outlets = {o.pk for o in rule.outlets.all()}
        categories = {c.pk for c in rule.categories.all()}
        if outlets and category.outlet_id not in outlets:
            continue
        if categories and category.pk not in categories:
            continue
        if rule.is_on(when):
            return rule
    return None


def adjust(amount: Decimal, rule: PriceRule | None) -> Decimal:
    if rule is None:
        return amount
    return max(Decimal("0"), (amount * (Decimal("100") + rule.percent) / Decimal("100")).quantize(CENT, ROUND_HALF_UP))


def current_prices(items, when=None) -> dict[int, tuple[Decimal, str, Decimal]]:
    """{item id: (price now, rule label or "", % change)} for the till's menu buttons."""
    rules = [r for r in PriceRule.objects.filter(is_active=True).prefetch_related("outlets", "categories")]
    when = timezone.localtime(when or timezone.now())
    running = [r for r in rules if r.is_on(when)]
    out = {}
    for item in items:
        rule = None
        for r in running:
            outlets = {o.pk for o in r.outlets.all()}
            categories = {c.pk for c in r.categories.all()}
            if (not outlets or item.category.outlet_id in outlets) and (not categories or item.category_id in categories):
                rule = r
                break
        out[item.pk] = (adjust(item.price, rule), rule.label if rule else "", rule.percent if rule else Decimal("0"))
    return out
