"""
Import lists from Excel (saved as CSV): menu items, stock items and guests.

Column names are matched loosely in English or Albanian ("name"/"emri", "price"/"çmimi" …).
Rows are added or updated by name, never deleted. Nothing is saved until the preview is confirmed.
"""

import csv
import io
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy


def _key(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in text if ch.isalnum())


KINDS = {
    "menu": {
        "label": gettext_lazy("Menu items"),
        "columns": ["outlet", "category", "name", "price", "name_en", "description", "available"],
        "required": ["outlet", "category", "name", "price"],
        "aliases": {
            "outlet": ["outlet", "pika", "pikaesherbimit", "lokali"],
            "category": ["category", "kategoria", "kategori"],
            "name": ["name", "emri", "artikulli", "item"],
            "price": ["price", "cmimi", "cmim"],
            "name_en": ["nameen", "englishname", "emrianglisht", "emriangl"],
            "description": ["description", "pershkrimi"],
            "available": ["available", "active", "aktiv", "nemenu"],
        },
    },
    "stock": {
        "label": gettext_lazy("Stock items"),
        "columns": ["name", "group", "unit", "in_stock", "reorder_level", "cost", "supplier"],
        "required": ["name"],
        "aliases": {
            "name": ["name", "emri", "artikulli"],
            "group": ["group", "grupi"],
            "unit": ["unit", "njesia"],
            "in_stock": ["instock", "stock", "stoku", "sasia", "quantity"],
            "reorder_level": ["reorderlevel", "minimum", "min", "nivelii porosise", "niveliporosise"],
            "cost": ["cost", "kosto", "cmimiblerjes", "price"],
            "supplier": ["supplier", "furnitori"],
        },
    },
    "guests": {
        "label": gettext_lazy("Guests"),
        "columns": [
            "first_name",
            "last_name",
            "email",
            "phone",
            "nationality",
            "document_type",
            "document_number",
            "date_of_birth",
            "company",
        ],
        "required": ["first_name", "last_name"],
        "aliases": {
            "first_name": ["firstname", "emri", "name"],
            "last_name": ["lastname", "mbiemri", "surname"],
            "email": ["email", "mail", "emaili"],
            "phone": ["phone", "telefoni", "tel", "mobile", "celulari"],
            "nationality": ["nationality", "country", "shtetesia", "shteti"],
            "document_type": ["documenttype", "llojiidokumentit", "dokumenti"],
            "document_number": ["documentnumber", "nrdokumentit", "numriidokumentit", "passport", "pasaporta", "id"],
            "date_of_birth": ["dateofbirth", "birthdate", "datelindja", "ditelindja"],
            "company": ["company", "kompania", "firma"],
        },
    },
}


@dataclass
class Parsed:
    kind: str
    rows: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    columns: dict = field(default_factory=dict)  # our column → header found
    unknown: list[str] = field(default_factory=list)


def template_csv(kind: str) -> str:
    return ";".join(KINDS[kind]["columns"]) + "\n"


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _decimal(value: str) -> Decimal:
    v = str(value).strip().replace("€", "").replace("L", "").replace(" ", "")
    if v.count(",") == 1 and v.count(".") <= 1 and v.rfind(",") > v.rfind("."):
        v = v.replace(".", "").replace(",", ".")  # 1.234,50
    else:
        v = v.replace(",", "")
    return Decimal(v)


def _date(value: str) -> date | None:
    v = str(value).strip()
    if not v:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(v)


def _bool(value: str) -> bool:
    return _key(value) not in {"0", "no", "jo", "false", "f", "n"}


def parse(kind: str, raw: bytes) -> Parsed:
    spec = KINDS[kind]
    text = _decode(raw)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), dialect)
    result = Parsed(kind)
    try:
        header = next(reader)
    except StopIteration:
        result.errors.append(_("The file is empty."))
        return result
    lookup = {}
    for i, h in enumerate(header):
        k = _key(h)
        for col, aliases in spec["aliases"].items():
            if col not in result.columns and (k == _key(col) or k in {_key(a) for a in aliases}):
                result.columns[col] = h
                lookup[col] = i
                break
        else:
            if h.strip():
                result.unknown.append(h.strip())
    missing = [c for c in spec["required"] if c not in lookup]
    if missing:
        result.errors.append(_("Missing columns: %(c)s") % {"c": ", ".join(missing)})
        return result
    for n, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        values = {col: (row[i].strip() if i < len(row) else "") for col, i in lookup.items()}
        try:
            result.rows.append(_clean(kind, values))
        except (ValueError, InvalidOperation) as e:
            result.errors.append(_("Row %(n)s: %(e)s") % {"n": n, "e": e})
        if len(result.rows) > 5000:
            result.errors.append(_("Only the first 5000 rows are imported."))
            break
    return result


def _clean(kind: str, v: dict) -> dict:
    for col in KINDS[kind]["required"]:
        if not v.get(col):
            raise ValueError(_("“%(c)s” is empty") % {"c": col})
    if kind == "menu":
        try:
            v["price"] = str(_decimal(v["price"]).quantize(Decimal("0.01")))
        except InvalidOperation:
            raise ValueError(_("price “%(p)s” is not a number") % {"p": v["price"]})
        v["available"] = _bool(v["available"]) if v.get("available") else True
    elif kind == "stock":
        for col in ("in_stock", "reorder_level", "cost"):
            if v.get(col):
                try:
                    v[col] = str(_decimal(v[col]))
                except InvalidOperation:
                    raise ValueError(_("“%(c)s” is not a number") % {"c": v[col]})
    elif kind == "guests":
        if v.get("date_of_birth"):
            try:
                v["date_of_birth"] = _date(v["date_of_birth"]).isoformat()
            except ValueError:
                raise ValueError(_("date of birth “%(d)s” is not a date (use 31.12.1990)") % {"d": v["date_of_birth"]})
    return v


@transaction.atomic
def apply(parsed: Parsed, user) -> dict:
    from apps.core.models import audit

    stats = {"created": 0, "updated": 0}
    fn = {"menu": _apply_menu, "stock": _apply_stock, "guests": _apply_guests}[parsed.kind]
    for row in parsed.rows:
        stats["created" if fn(row) else "updated"] += 1
    audit(user, f"import.{parsed.kind}", f"+{stats['created']} ~{stats['updated']}")
    return stats


def _apply_menu(r: dict) -> bool:
    from apps.outlets.models import Category, Item, Outlet

    outlet = Outlet.objects.filter(name__iexact=r["outlet"]).first() or Outlet.objects.create(name=r["outlet"])
    category = Category.objects.filter(outlet=outlet, name__iexact=r["category"]).first() or Category.objects.create(
        outlet=outlet, name=r["category"], sort_order=outlet.categories.count()
    )
    item = Item.objects.filter(category__outlet=outlet, name__iexact=r["name"]).first()
    created = item is None
    item = item or Item(name=r["name"], sort_order=category.items.count())
    item.category = category
    item.price = Decimal(r["price"])
    item.is_active = r["available"]
    for f in ("name_en", "description"):
        if r.get(f):
            setattr(item, f, r[f][:255])
    item.save()
    return created


def _apply_stock(r: dict) -> bool:
    from apps.inventory import services as inv
    from apps.inventory.models import StockItem, StockMove, Supplier

    groups = {_key(v): k for k, v in StockItem.Group.choices} | {_key(k): k for k in StockItem.Group.values}
    units = {_key(v): k for k, v in StockItem.Unit.choices} | {_key(k): k for k in StockItem.Unit.values}
    item = StockItem.objects.filter(name__iexact=r["name"]).first()
    created = item is None
    item = item or StockItem(name=r["name"][:120])
    if r.get("group"):
        item.group = groups.get(_key(r["group"]), item.group)
    if r.get("unit"):
        item.unit = units.get(_key(r["unit"]), item.unit)
    if r.get("reorder_level"):
        item.min_level = Decimal(r["reorder_level"])
    if r.get("cost"):
        item.cost = Decimal(r["cost"])
    if r.get("supplier"):
        item.supplier = Supplier.objects.filter(name__iexact=r["supplier"]).first() or Supplier.objects.create(
            name=r["supplier"][:120]
        )
    item.save()
    if r.get("in_stock"):
        diff = Decimal(r["in_stock"]) - item.on_hand
        if diff:
            inv._move(item, StockMove.Kind.ADJUST, diff, note=_("Imported from a file"))
    return created


def _apply_guests(r: dict) -> bool:
    from apps.frontdesk.models import Guest

    qs = Guest.objects.filter(first_name__iexact=r["first_name"], last_name__iexact=r["last_name"])
    if r.get("email"):
        qs = qs.filter(email__iexact=r["email"])
    elif r.get("phone"):
        qs = qs.filter(phone=r["phone"])
    guest = qs.first()
    created = guest is None
    guest = guest or Guest(first_name=r["first_name"][:80], last_name=r["last_name"][:80])
    doc_types = {_key(v): k for k, v in Guest.DocumentType.choices} | {_key(k): k for k in Guest.DocumentType.values}
    doc_types |= {"pasaporte": "passport", "pasaporta": "passport", "karteidentiteti": "id_card", "id": "id_card"}
    for f in ("email", "phone", "nationality", "document_number", "company"):
        if r.get(f):
            setattr(guest, f, r[f][: Guest._meta.get_field(f).max_length])
    if r.get("document_type"):
        guest.document_type = doc_types.get(_key(r["document_type"]), "other")
    if r.get("date_of_birth"):
        guest.date_of_birth = date.fromisoformat(r["date_of_birth"])
    guest.save()
    return created
