"""
Moving stock between the owner's businesses (each has its own InnKeeper).

The sender picks the items and quantities: they leave its stock at its average cost, and InnKeeper gives a
transfer code (and a file) holding the list. The receiver pastes the code or opens the file, checks which
of its own stock items each line is, and takes them in at the same cost, like a delivery. A code can be
received only once.

Between separate companies this is a sale for tax purposes: the invoice is made as usual; InnKeeper only
moves the stock.
"""

import base64
import json
import secrets
import zlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings, audit

from . import services
from .models import StockItem, StockMove, StockTransfer, Supplier

PREFIX = "IKT1."
CENT = Decimal("0.01")


def new_code() -> str:
    return "T-" + secrets.token_hex(3).upper()


@transaction.atomic
def send(quantities: dict[int, Decimal], *, to: str, note: str = "", user) -> StockTransfer:
    to = (to or "").strip()
    if not to:
        raise BusinessError(_("Write which business the goods go to."))
    taken = {pk: q for pk, q in quantities.items() if q}
    if not taken:
        raise BusinessError(_("Enter how much of at least one item is sent."))
    if any(q < 0 for q in taken.values()):
        raise BusinessError(_("Quantities can't be negative."))
    items = {i.pk: i for i in StockItem.objects.select_for_update().filter(pk__in=taken)}
    short = [i.name for pk, i in items.items() if taken[pk] > i.on_hand]
    if short:
        raise BusinessError(_("Not that much in stock: %(items)s.") % {"items": ", ".join(short)})
    code = new_code()
    while StockTransfer.objects.filter(code=code).exists():
        code = new_code()
    t = StockTransfer.objects.create(code=code, direction=StockTransfer.Direction.OUT, other=to[:120], note=note[:255], created_by=user)
    lines, total = [], Decimal("0")
    for pk, q in taken.items():
        item = items[pk]
        services._move(item, StockMove.Kind.TRANSFER, -q, user=user, unit_cost=item.cost, transfer=t, note=_("To %(b)s") % {"b": t.other})
        lines.append({"name": item.name, "unit": item.unit, "quantity": str(q), "unit_cost": str(item.cost)})
        total += q * item.cost
    t.lines, t.total = lines, total.quantize(CENT)
    t.save(update_fields=["lines", "total"])
    audit(user, "stock.transfer_out", f"{code} → {t.other}: {t.total}", t)
    return t


def encode(t: StockTransfer) -> str:
    """The transfer as one line of text, to paste in the other InnKeeper."""
    payload = {"v": 1, "code": t.code, "from": HotelSettings.load().name, "date": t.business_date.isoformat(), "note": t.note, "lines": t.lines}
    raw = zlib.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    return PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@dataclass
class IncomingLine:
    name: str
    unit: str
    quantity: Decimal
    unit_cost: Decimal
    match: StockItem | None

    @property
    def unit_label(self) -> str:
        return unit_label(self.unit)


def unit_label(unit: str) -> str:
    return str(dict(StockItem.Unit.choices).get(unit, unit))


def decode(text: str) -> dict:
    text = "".join((text or "")[:200_000].split())
    if not text.startswith(PREFIX):
        raise BusinessError(_("This is not an InnKeeper transfer code."))
    body = text[len(PREFIX):]
    try:
        unzip = zlib.decompressobj()
        raw = unzip.decompress(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)), 1 << 20)  # at most 1 MB
        if unzip.unconsumed_tail:
            raise ValueError
        data = json.loads(raw.decode("utf-8"))
        lines = []
        for ln in data["lines"][:300]:
            q, c = Decimal(str(ln["quantity"])), Decimal(str(ln["unit_cost"]))
            if q <= 0 or c < 0:
                raise ValueError
            lines.append({"name": str(ln["name"])[:120], "unit": str(ln.get("unit", ""))[:10], "quantity": q, "unit_cost": c})
        code = str(data["code"])[:20]
        sender = str(data["from"])[:120]
    except (ValueError, KeyError, TypeError, zlib.error, InvalidOperation, UnicodeDecodeError, json.JSONDecodeError):
        raise BusinessError(_("The transfer code is damaged. Copy it again, whole."))
    if not lines:
        raise BusinessError(_("The transfer is empty."))
    return {"code": code, "from": sender, "date": str(data.get("date", ""))[:10], "note": str(data.get("note", ""))[:255], "lines": lines}


def preview(data: dict) -> list[IncomingLine]:
    by_name = {i.name.lower(): i for i in StockItem.objects.filter(is_active=True)}
    return [IncomingLine(ln["name"], ln["unit"], ln["quantity"], ln["unit_cost"], by_name.get(ln["name"].lower())) for ln in data["lines"]]


@transaction.atomic
def receive(data: dict, matches: list[int | None], *, user) -> StockTransfer:
    """Take the goods in. `matches` is our stock item for each line (None: create it with the sender's name)."""
    if StockTransfer.objects.select_for_update().filter(code=data["code"], direction=StockTransfer.Direction.IN).exists():
        raise BusinessError(_("Transfer %(c)s has already been received.") % {"c": data["code"]})
    if len(matches) != len(data["lines"]):
        raise BusinessError(_("Something changed. Paste the code again."))
    supplier, _created = Supplier.objects.get_or_create(name=data["from"][:120] or _("Another business"))
    lines = []
    for ln, pk in zip(data["lines"], matches):
        if pk:
            item = StockItem.objects.get(pk=pk)
        else:
            item = StockItem.objects.filter(name__iexact=ln["name"]).first() or StockItem.objects.create(
                name=ln["name"], unit=ln["unit"] if ln["unit"] in StockItem.Unit.values else StockItem.Unit.PIECE, cost=ln["unit_cost"]
            )
        lines.append(services.DeliveryLine(item, ln["quantity"], ln["unit_cost"]))
    delivery = services.receive_delivery(lines, user=user, supplier=supplier, reference=data["code"], note=_("Transfer from %(b)s") % {"b": data["from"]})
    t = StockTransfer.objects.create(
        code=data["code"], direction=StockTransfer.Direction.IN, other=data["from"][:120], note=data["note"],
        lines=[{"name": ln["name"], "unit": ln["unit"], "quantity": str(ln["quantity"]), "unit_cost": str(ln["unit_cost"])} for ln in data["lines"]],
        total=delivery.total, delivery=delivery, created_by=user,
    )
    audit(user, "stock.transfer_in", f"{t.code} ← {t.other}: {t.total}", t)
    return t
