from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.core.models import HotelSettings

register = template.Library()

THIN_SPACE = "\u202f"
NBSP = "\u00a0"


@register.filter
def money(value, symbol=None):
    """Format a number as money using the hotel's currency: 1 234.50 €"""
    if value in (None, ""):
        return "—"
    try:
        amount = Decimal(value).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return value
    symbol = symbol if symbol is not None else HotelSettings.load().currency_symbol
    sign = "-" if amount < 0 else ""
    whole, frac = f"{abs(amount):.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return f"{sign}{THIN_SPACE.join(groups)}.{frac}{NBSP}{symbol}".strip()


@register.simple_tag
def icon(name, extra_class=""):
    return format_html('<svg class="icon {}" aria-hidden="true"><use href="#i-{}"></use></svg>', extra_class, name)


@register.simple_tag
def status_badge(value, label=None, css=None):
    return format_html('<span class="badge b-{}">{}</span>', css or value, label if label is not None else value)


@register.simple_tag(takes_context=True)
def active(context, *prefixes):
    path = context["request"].path
    return mark_safe("active") if any(path.startswith(p) for p in prefixes) else ""


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def percent_of(value, total):
    """Percentage for CSS widths/heights. Returns e.g. "42.5" (always a dot, never a locale comma)."""
    try:
        total = float(total)
        pct = 0.0 if total == 0 else max(0.0, min(100.0, float(value) * 100 / total))
    except (TypeError, ValueError):
        pct = 0.0
    return f"{pct:.1f}"


@register.filter
def absval(value):
    try:
        return abs(value)
    except TypeError:
        return value
