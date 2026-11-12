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


@register.filter
def qty(value):
    """A stock quantity without needless zeros: 4.600 → 4.6, 12.000 → 12 (in the user's number format)."""
    from django.utils.formats import number_format

    if value in (None, ""):
        return "—"
    try:
        d = Decimal(value).normalize()
    except (InvalidOperation, TypeError, ValueError):
        return value
    if d == d.to_integral():
        d = d.quantize(Decimal("1"))
    return number_format(d, use_l10n=True)


@register.filter
def stamp_range(n):
    try:
        return range(min(int(n), 30))
    except (TypeError, ValueError):
        return range(0)


@register.filter
def mul(a, b):
    """a × b as money-safe decimals (quantity × price)."""
    try:
        return (Decimal(str(a)) * Decimal(str(b))).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return ""


@register.filter
def release_notes(text):
    """GitHub release notes (simple Markdown) as safe HTML, only in the reader's language (Shqip / English)."""
    import re

    from django.utils.html import escape
    from django.utils.translation import get_language

    text = (text or "").replace("\r\n", "\n")
    # The notes hold "**Shqip**" and "**English**" sections; keep the one for the reader.
    parts = re.split(r"^\*\*(Shqip|English)\*\*\s*$", text, flags=re.M)
    if len(parts) >= 5:
        sections = dict(zip(parts[1::2], parts[2::2]))
        want = "Shqip" if (get_language() or "").startswith("sq") else "English"
        body = sections.get(want, "")
        # The install steps ("### Install or update ...") are for the download page, not this one.
        text = re.split(r"^###\s", body, flags=re.M)[0]

    def inline(s):
        s = escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\[([^\]]+)\]\((https://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
        return s

    out, in_list = [], False
    for line in text.split("\n"):
        line = line.rstrip()
        item = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)", line)
        if item:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(item.group(1))}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        head = re.match(r"^(#{1,6})\s+(.*)", line)
        if head:
            out.append(f"<h4>{inline(head.group(2))}</h4>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return mark_safe("".join(out))
