"""
Backups and moving to another computer.

* **Full backup** – everything: settings, rooms, menus, staff (with encrypted
  passwords), guests, reservations, bills, receipts, expenses, activity log.
  Restoring it replaces all current data.
* **Settings export** – only the configuration (business details, rooms and
  rates, outlets, menus, tables, floor plans). Importing it adds or updates
  those items and never touches guests or money.

Files are gzip-compressed JSON (`.innkeeper`), readable by any future version.
"""

import gzip
import json
from datetime import datetime
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core import serializers
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils import timezone

from apps import __version__

FORMAT = "innkeeper-backup"

# Models in dependency order (parents first). Restore inserts in this order and deletes in reverse.
FULL_MODELS = [
    "accounts.User",
    "core.HotelSettings",
    "core.Sequence",
    "core.AuditLog",
    "frontdesk.RoomType",
    "frontdesk.Room",
    "frontdesk.CalendarFeed",
    "frontdesk.Guest",
    "frontdesk.Reservation",
    "frontdesk.Group",
    "frontdesk.ChannelBooking",
    "frontdesk.SeasonRate",
    "outlets.Printer",
    "outlets.Station",
    "outlets.Outlet",
    "outlets.Category",
    "outlets.Item",
    "outlets.Table",
    "outlets.Order",
    "outlets.KitchenTicket",
    "outlets.OrderLine",
    "finance.Folio",
    "finance.Charge",
    "finance.Payment",
    "finance.Expense",
    "finance.DayClose",
    "housekeeping.HousekeepingTask",
    "housekeeping.MaintenanceTicket",
    "inventory.Supplier",
    "inventory.StockItem",
    "inventory.RecipeLine",
    "inventory.Delivery",
    "inventory.StockCount",
    "inventory.StockMove",
    "payments.PaymentLink",
]

# Not worth moving: print history (kept 3 days).
NOT_BACKED_UP = {"outlets.PrintJob", "frontdesk.ChannelSyncState"}

SETTINGS_FIELDS_SKIP = {
    "id",
    "setup_completed",
    "updated_at",
    "smtp_password",
    "onboarding_dismissed",
    # Secrets stay on the machine they were entered on; they are re-entered after moving.
    "pok_key_secret",
    "paysera_password",
    "channex_api_key",
}


class BackupError(Exception):
    pass


def _models(labels):
    return [apps.get_model(label) for label in labels]


def _wrap(kind: str, payload) -> bytes:
    doc = {
        "format": FORMAT,
        "kind": kind,
        "version": __version__,
        "created": timezone.now().isoformat(),
        "data": payload,
    }
    return gzip.compress(json.dumps(doc, ensure_ascii=False, default=str).encode("utf-8"))


def read_file(raw: bytes) -> dict:
    try:
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass  # plain JSON is accepted too
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise BackupError("not-a-backup") from e
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or doc.get("kind") not in {"full", "settings"}:
        raise BackupError("not-a-backup")
    return doc


def filename(kind: str) -> str:
    return f"innkeeper-{kind}-{datetime.now():%Y-%m-%d_%H%M}.innkeeper"


# ---------- Full backup ----------


def export_full() -> bytes:
    data = []
    for model in _models(FULL_MODELS):
        data.extend(json.loads(serializers.serialize("json", model._default_manager.all().order_by("pk"))))
    return _wrap("full", data)


def summarize(doc: dict) -> dict:
    counts: dict[str, int] = {}
    if doc["kind"] == "full":
        for obj in doc["data"]:
            counts[obj["model"]] = counts.get(obj["model"], 0) + 1
    else:
        for key, rows in doc["data"].items():
            counts[key] = len(rows) if isinstance(rows, list) else 1
    name = ""
    if doc["kind"] == "full":
        hs = next((o for o in doc["data"] if o["model"] == "core.hotelsettings"), None)
        name = hs["fields"].get("name", "") if hs else ""
    else:
        name = doc["data"].get("hotel", {}).get("name", "")
    return {
        "kind": doc["kind"],
        "created": doc.get("created", ""),
        "version": doc.get("version", ""),
        "name": name,
        "counts": counts,
    }


@transaction.atomic
def restore_full(doc: dict) -> None:
    if doc["kind"] != "full":
        raise BackupError("wrong-kind")
    objects = list(serializers.deserialize("json", json.dumps(doc["data"]), ignorenonexistent=True))
    models = _models(FULL_MODELS)
    for model in reversed(models):
        model._default_manager.all().delete()
    Session.objects.all().delete()
    order = {m._meta.label_lower: i for i, m in enumerate(models)}
    objects.sort(key=lambda o: order.get(o.object._meta.label_lower, 999))
    for obj in objects:
        obj.save()
    # Make sure new rows get ids after the restored ones (PostgreSQL sequences).
    statements = connection.ops.sequence_reset_sql(no_style(), models)
    with connection.cursor() as cursor:
        for sql in statements:
            cursor.execute(sql)


# ---------- Settings export / import ----------


def export_settings() -> bytes:
    from apps.core.models import HotelSettings
    from apps.frontdesk.models import CalendarFeed, Room, RoomType, SeasonRate
    from apps.outlets.models import Outlet, Printer, Station

    hs = HotelSettings.load()
    hotel = {f.name: getattr(hs, f.name) for f in hs._meta.concrete_fields if f.name not in SETTINGS_FIELDS_SKIP}
    payload = {
        "hotel": {
            k: (v.isoformat() if hasattr(v, "isoformat") else str(v) if not isinstance(v, (bool, int, str)) else v)
            for k, v in hotel.items()
        },
        "room_types": [
            {
                "code": t.code,
                "name": t.name,
                "description": t.description,
                "base_rate": str(t.base_rate),
                "max_adults": t.max_adults,
                "max_children": t.max_children,
                "is_active": t.is_active,
                "name_en": t.name_en,
                "description_en": t.description_en,
                "bookable_online": t.bookable_online,
                "photo": t.photo,
                "sort_order": t.sort_order,
            }
            for t in RoomType.objects.all()
        ],
        "seasons": [
            {
                "name": x.name,
                "room_type": x.room_type.code if x.room_type_id else None,
                "start_date": x.start_date.isoformat(),
                "end_date": x.end_date.isoformat(),
                "rate": str(x.rate) if x.rate is not None else None,
                "percent": str(x.percent) if x.percent is not None else None,
                "min_nights": x.min_nights,
                "is_active": x.is_active,
            }
            for x in SeasonRate.objects.select_related("room_type")
        ],
        "calendars": [
            {"room": f.room.number, "source": f.source, "url": f.url, "is_active": f.is_active}
            for f in CalendarFeed.objects.select_related("room")
        ],
        "printers": [
            {
                f: getattr(p, f)
                for f in (
                    "name",
                    "connection",
                    "address",
                    "port",
                    "system_name",
                    "paper_width",
                    "open_drawer",
                    "is_active",
                )
            }
            for p in Printer.objects.all()
        ],
        "stations": [
            {
                "name": st.name,
                "printer": st.printer.name if st.printer_id else None,
                "sort_order": st.sort_order,
                "is_active": st.is_active,
            }
            for st in Station.objects.select_related("printer")
        ],
        "rooms": [
            {
                "number": r.number,
                "room_type": r.room_type.code,
                "floor": r.floor,
                "notes": r.notes,
                "is_active": r.is_active,
            }
            for r in Room.objects.select_related("room_type")
        ],
        "outlets": [],
    }
    for o in Outlet.objects.select_related("receipt_printer").prefetch_related("categories__items", "tables"):
        payload["outlets"].append(
            {
                "name": o.name,
                "kind": o.kind,
                "uses_tables": o.uses_tables,
                "sort_order": o.sort_order,
                "is_active": o.is_active,
                "menu_public": o.menu_public,
                "menu_intro": o.menu_intro,
                "receipt_printer": o.receipt_printer.name if o.receipt_printer_id else None,
                "auto_print_receipt": o.auto_print_receipt,
                "categories": [
                    {
                        "name": c.name,
                        "name_en": c.name_en,
                        "sort_order": c.sort_order,
                        "station": c.station.name if c.station_id else None,
                        "items": [
                            {
                                "name": i.name,
                                "name_en": i.name_en,
                                "description": i.description,
                                "description_en": i.description_en,
                                "price": str(i.price),
                                "duration_minutes": i.duration_minutes,
                                "sort_order": i.sort_order,
                                "is_active": i.is_active,
                            }
                            for i in c.items.all()
                        ],
                    }
                    for c in o.categories.all()
                ],
                "tables": [
                    {
                        "name": t.name,
                        "seats": t.seats,
                        "zone": t.zone,
                        "shape": t.shape,
                        "pos_x": t.pos_x,
                        "pos_y": t.pos_y,
                        "width": t.width,
                        "height": t.height,
                        "sort_order": t.sort_order,
                        "is_active": t.is_active,
                    }
                    for t in o.tables.all()
                ],
            }
        )
    from apps.inventory.models import RecipeLine, StockItem, Supplier

    payload["suppliers"] = [
        {f: getattr(x, f) for f in ("name", "contact", "phone", "email", "tax_id", "notes", "is_active")}
        for x in Supplier.objects.all()
    ]
    payload["stock_items"] = [
        {
            "name": x.name,
            "group": x.group,
            "unit": x.unit,
            "min_level": str(x.min_level),
            "cost": str(x.cost),
            "supplier": x.supplier.name if x.supplier_id else None,
            "is_active": x.is_active,
        }
        for x in StockItem.objects.select_related("supplier")
    ]
    payload["recipes"] = [
        {
            "outlet": r.item.category.outlet.name,
            "category": r.item.category.name,
            "item": r.item.name,
            "stock_item": r.stock_item.name,
            "quantity": str(r.quantity),
        }
        for r in RecipeLine.objects.select_related("item__category__outlet", "stock_item")
    ]
    return _wrap("settings", payload)


@transaction.atomic
def import_settings(doc: dict) -> dict:
    """Add or update configuration by natural keys (codes, numbers and names). Never deletes anything."""
    from decimal import Decimal

    from apps.core.models import HotelSettings
    from apps.frontdesk.models import CalendarFeed, Room, RoomType, SeasonRate
    from apps.outlets.models import Category, Item, Outlet, Printer, Station, Table

    if doc["kind"] != "settings":
        raise BackupError("wrong-kind")
    data = doc["data"]
    stats = {"room_types": 0, "rooms": 0, "outlets": 0, "items": 0, "tables": 0}

    hs = HotelSettings.load()
    for field in hs._meta.concrete_fields:
        if field.name in SETTINGS_FIELDS_SKIP or field.name not in data.get("hotel", {}):
            continue
        setattr(hs, field.name, field.to_python(data["hotel"][field.name]))
    hs.setup_completed = True
    hs.save()

    types = {}
    for t in data.get("room_types", []):
        obj, _c = RoomType.objects.update_or_create(
            code=t["code"],
            defaults={k: (Decimal(v) if k == "base_rate" else v) for k, v in t.items() if k != "code"},
        )
        types[obj.code] = obj
        stats["room_types"] += 1
    for r in data.get("rooms", []):
        rt = types.get(r["room_type"]) or RoomType.objects.filter(code=r["room_type"]).first()
        if rt is None:
            continue
        Room.objects.update_or_create(
            number=r["number"],
            defaults={
                "room_type": rt,
                "floor": r.get("floor", 1),
                "notes": r.get("notes", ""),
                "is_active": r.get("is_active", True),
            },
        )
        stats["rooms"] += 1
    for x in data.get("seasons", []):
        rt = (
            types.get(x["room_type"]) or RoomType.objects.filter(code=x["room_type"]).first()
            if x["room_type"]
            else None
        )
        SeasonRate.objects.update_or_create(
            name=x["name"],
            room_type=rt,
            start_date=x["start_date"],
            defaults={
                "end_date": x["end_date"],
                "rate": Decimal(x["rate"]) if x.get("rate") else None,
                "percent": Decimal(x["percent"]) if x.get("percent") else None,
                "min_nights": x.get("min_nights", 1),
                "is_active": x.get("is_active", True),
            },
        )
    for f in data.get("calendars", []):
        room = Room.objects.filter(number=f["room"]).first()
        if room:
            CalendarFeed.objects.update_or_create(
                room=room, url=f["url"], defaults={"source": f["source"], "is_active": f.get("is_active", True)}
            )
    printers = {}
    for p in data.get("printers", []):
        printers[p["name"]], _c = Printer.objects.update_or_create(
            name=p["name"], defaults={k: v for k, v in p.items() if k != "name"}
        )
    stations = {}
    for st in data.get("stations", []):
        stations[st["name"]], _c = Station.objects.update_or_create(
            name=st["name"],
            defaults={
                "printer": printers.get(st.get("printer")),
                "sort_order": st.get("sort_order", 0),
                "is_active": st.get("is_active", True),
            },
        )
    for o in data.get("outlets", []):
        defaults = {
            k: o[k]
            for k in (
                "kind",
                "uses_tables",
                "sort_order",
                "is_active",
                "menu_public",
                "menu_intro",
                "auto_print_receipt",
            )
            if k in o
        }
        if "receipt_printer" in o:
            defaults["receipt_printer"] = printers.get(o["receipt_printer"])
        outlet, _c = Outlet.objects.update_or_create(name=o["name"], defaults=defaults)
        stats["outlets"] += 1
        for c in o.get("categories", []):
            cat, _c = Category.objects.update_or_create(
                outlet=outlet,
                name=c["name"],
                defaults={
                    "name_en": c.get("name_en", ""),
                    "sort_order": c.get("sort_order", 0),
                    "station": stations.get(c.get("station"))
                    or Station.objects.filter(name=c.get("station") or "").first(),
                },
            )
            for i in c.get("items", []):
                Item.objects.update_or_create(
                    category=cat,
                    name=i["name"],
                    defaults={k: (Decimal(v) if k == "price" else v) for k, v in i.items() if k != "name"},
                )
                stats["items"] += 1
        for t in o.get("tables", []):
            Table.objects.update_or_create(
                outlet=outlet, name=t["name"], defaults={k: v for k, v in t.items() if k != "name"}
            )
            stats["tables"] += 1
    _import_stock_settings(data)
    return stats


def _import_stock_settings(data: dict) -> None:
    from decimal import Decimal

    from apps.inventory.models import RecipeLine, StockItem, Supplier
    from apps.outlets.models import Item

    suppliers = {}
    for x in data.get("suppliers", []):
        suppliers[x["name"]], _c = Supplier.objects.update_or_create(
            name=x["name"], defaults={k: v for k, v in x.items() if k != "name"}
        )
    stock = {}
    for x in data.get("stock_items", []):
        stock[x["name"]], _c = StockItem.objects.update_or_create(
            name=x["name"],
            defaults={
                "group": x.get("group", "food"),
                "unit": x.get("unit", "pcs"),
                "min_level": Decimal(x.get("min_level") or "0"),
                "cost": Decimal(x.get("cost") or "0"),
                "supplier": suppliers.get(x.get("supplier")),
                "is_active": x.get("is_active", True),
            },
        )
    for r in data.get("recipes", []):
        item = Item.objects.filter(
            name=r["item"], category__name=r["category"], category__outlet__name=r["outlet"]
        ).first()
        stock_item = stock.get(r["stock_item"]) or StockItem.objects.filter(name=r["stock_item"]).first()
        if item and stock_item:
            RecipeLine.objects.update_or_create(
                item=item, stock_item=stock_item, defaults={"quantity": Decimal(r["quantity"])}
            )


# ---------- Automatic backups on disk ----------


def backup_dir() -> Path:
    path = Path(getattr(settings, "INNKEEPER_BACKUP_DIR", settings.BASE_DIR / "backups"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_backup_to_disk(prefix: str = "auto", keep: int = 30) -> Path:
    """Write a full backup into the backup folder and keep only the newest `keep` automatic ones."""
    path = backup_dir() / f"{prefix}-{datetime.now():%Y-%m-%d_%H%M%S}.innkeeper"
    path.write_bytes(export_full())
    old = sorted(backup_dir().glob(f"{prefix}-*.innkeeper"))
    for f in old[:-keep] if keep else []:
        f.unlink(missing_ok=True)
    return path


def disk_backups() -> list[dict]:
    files = sorted(backup_dir().glob("*.innkeeper"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {"name": f.name, "size": f.stat().st_size, "modified": datetime.fromtimestamp(f.stat().st_mtime)}
        for f in files[:30]
    ]
