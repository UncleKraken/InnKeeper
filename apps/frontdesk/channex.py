"""
Channel manager connection through Channex (channex.io).

Booking.com, Airbnb, Expedia and others only open their APIs to certified partners. Channex is one,
and offers a public API for property software. InnKeeper:

* **sends** availability (free rooms per room type), prices per night (base rate + seasons) and minimum
  stays, for the next `channex_days_ahead` days, whenever something changes and as a full refresh;
* **receives** bookings from Channex's booking-revisions feed (new, changed, cancelled), turns them into
  reservations on a free room of the right type, and acknowledges each revision.

Room types are linked to Channex room types and rate plans in Rooms & rates → Channel manager.
"""

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import HotelSettings, audit

from . import services
from .booking import free_rooms
from .models import ChannelBooking, ChannelSyncState, Guest, Reservation, Room, RoomType
from .pricing import quote

log = logging.getLogger(__name__)
_lock = threading.Lock()
_pull_lock = threading.Lock()  # webhook, background job and the button may pull at once

OTA_SOURCES = {
    "booking.com": Reservation.Source.BOOKING_COM,
    "bookingcom": Reservation.Source.BOOKING_COM,
    "airbnb": Reservation.Source.AIRBNB,
    "expedia": Reservation.Source.EXPEDIA,
}


class ChannexError(Exception):
    pass


class Client:
    def __init__(self, api_key: str, staging: bool = False):
        self.api_key = api_key
        self.base = "https://staging.channex.io/api/v1" if staging else "https://app.channex.io/api/v1"

    @classmethod
    def from_settings(cls, hs: HotelSettings | None = None) -> "Client":
        hs = hs or HotelSettings.load()
        return cls(hs.channex_api_key, hs.channex_staging)

    def request(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("user-api-key", self.api_key)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  (fixed Channex URL)
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read()[:400].decode("utf-8", "replace")
            if e.code == 401:
                raise ChannexError(_("Channex refused the API key.")) from e
            raise ChannexError(f"HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ChannexError(str(getattr(e, "reason", e))) from e
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError as e:
            raise ChannexError("Unexpected answer from Channex") from e

    # Catalogue (for linking room types)
    def room_types(self, property_id: str) -> list[dict]:
        res = self.request("GET", "/room_types", params={"filter[property_id]": property_id, "pagination[limit]": 100})
        return [{"id": x["id"], **x.get("attributes", {})} for x in res.get("data", [])]

    def rate_plans(self, property_id: str) -> list[dict]:
        res = self.request("GET", "/rate_plans", params={"filter[property_id]": property_id, "pagination[limit]": 100})
        return [{"id": x["id"], **x.get("attributes", {})} for x in res.get("data", [])]

    # ARI
    def availability(self, values: list[dict]) -> dict:
        return self.request("POST", "/availability", {"values": values})

    def restrictions(self, values: list[dict]) -> dict:
        return self.request("POST", "/restrictions", {"values": values})

    # Bookings
    def feed(self, property_id: str) -> list[dict]:
        res = self.request(
            "GET", "/booking_revisions/feed", params={"filter[property_id]": property_id, "order[inserted_at]": "asc"}
        )
        return [{"id": x["id"], **x.get("attributes", {})} for x in res.get("data", [])]

    def ack(self, revision_id: str) -> None:
        self.request("POST", f"/booking_revisions/{urllib.parse.quote(revision_id)}/ack")


# ---------- Availability, rates and restrictions ----------


def _runs(days: list[date], values: list) -> list[tuple[date, date, object]]:
    """Group consecutive days with the same value: [(from, to, value), ...] (to is inclusive)."""
    out: list[tuple[date, date, object]] = []
    for d, v in zip(days, values):
        if out and out[-1][2] == v and out[-1][1] + timedelta(days=1) == d:
            out[-1] = (out[-1][0], d, v)
        else:
            out.append((d, d, v))
    return out


def free_counts(room_type: RoomType, start: date, days: int) -> list[int]:
    rooms = list(
        Room.objects.filter(room_type=room_type, is_active=True, out_of_order=False).values_list("pk", flat=True)
    )
    end = start + timedelta(days=days)
    taken = [0] * days
    for arrival, departure in Reservation.objects.filter(
        room_id__in=rooms, status__in=Reservation.ACTIVE_STATUSES, arrival__lt=end, departure__gt=start
    ).values_list("arrival", "departure"):
        for i in range(max(0, (arrival - start).days), min(days, (departure - start).days)):
            taken[i] += 1
    return [max(0, len(rooms) - t) for t in taken]


def build_ari(start: date | None = None, days: int | None = None) -> tuple[list[dict], list[dict]]:
    hs = HotelSettings.load()
    start = start or timezone.localdate()
    days = days or hs.channex_days_ahead
    dates = [start + timedelta(days=i) for i in range(days)]
    availability, restrictions = [], []
    for rt in RoomType.objects.exclude(channex_room_type_id=""):
        counts = free_counts(rt, start, days) if rt.is_active else [0] * days
        for a, b, v in _runs(dates, counts):
            availability.append(
                {
                    "property_id": hs.channex_property_id,
                    "room_type_id": rt.channex_room_type_id,
                    "date_from": a.isoformat(),
                    "date_to": b.isoformat(),
                    "availability": v,
                }
            )
        if rt.channex_rate_plan_id:
            q = quote(rt, start, start + timedelta(days=days))
            pairs = [(f"{p:.2f}", m) for p, m in zip(q.nightly, q.night_min_stay)]
            for a, b, (rate, min_stay) in _runs(dates, pairs):
                restrictions.append(
                    {
                        "property_id": hs.channex_property_id,
                        "rate_plan_id": rt.channex_rate_plan_id,
                        "date_from": a.isoformat(),
                        "date_to": b.isoformat(),
                        "rate": rate,
                        "min_stay_arrival": min_stay,
                    }
                )
    return availability, restrictions


def push(force: bool = False) -> bool:
    """Send availability and prices if anything changed (or always with force). Returns True if sent."""
    hs = HotelSettings.load()
    if not hs.channex_configured:
        return False
    state = ChannelSyncState.get()
    if not (force or state.dirty):
        return False
    ChannelSyncState.objects.filter(pk=1).update(dirty=False)  # changes from now on mark it dirty again
    availability, restrictions = build_ari()
    client = Client.from_settings(hs)
    try:
        for chunk in _chunks(availability, 500):
            client.availability(chunk)
        for chunk in _chunks(restrictions, 500):
            client.restrictions(chunk)
    except ChannexError as e:
        ChannelSyncState.objects.filter(pk=1).update(dirty=True, last_error=str(e)[:255])
        log.warning("Channex push failed: %s", e)
        raise
    ChannelSyncState.objects.filter(pk=1).update(last_push=timezone.now(), last_error="")
    return True


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def mark_dirty() -> None:
    """Something changed that affects availability or prices: send it soon."""
    if not HotelSettings.load().channex_configured:
        return
    ChannelSyncState.objects.update_or_create(pk=1, defaults={"dirty": True})
    if getattr(settings, "CHANNEX_BACKGROUND", True):
        transaction.on_commit(_push_soon)


def _push_soon() -> None:
    def run():
        from django.db import connection

        if not _lock.acquire(blocking=False):
            return  # a push is already running; it will pick up the change or the next loop will
        try:
            push()
        except Exception as e:  # never break the request that triggered it
            log.warning("Background channel push failed: %s", e)
        finally:
            _lock.release()
            connection.close()

    threading.Thread(target=run, daemon=True).start()


# ---------- Bookings ----------


def _source(ota_name: str) -> str:
    key = (ota_name or "").strip().lower()
    for k, v in OTA_SOURCES.items():
        if k in key:
            return v
    return Reservation.Source.OTHER


def _guest(customer: dict, channel: str) -> Guest:
    first = (customer.get("name") or "").strip()[:80] or channel
    last = (customer.get("surname") or "").strip()[:80] or _("guest")
    mail = (customer.get("mail") or "").strip()[:254]
    if mail:
        existing = Guest.objects.filter(email__iexact=mail, first_name__iexact=first, last_name__iexact=last).first()
        if existing:
            return existing
    return Guest.objects.create(
        first_name=first,
        last_name=last,
        email=mail,
        phone=(customer.get("phone") or "")[:40],
        nationality=(customer.get("country") or "")[:60],
        address=", ".join(x for x in (customer.get("address"), customer.get("city"), customer.get("zip")) if x)[:255],
    )


def _nightly(room: dict, arrival: date, departure: date) -> list[str]:
    days = room.get("days") or {}
    out = []
    d = arrival
    while d < departure:
        v = days.get(d.isoformat())
        if v is None:
            return []
        out.append(f"{Decimal(str(v)):.2f}")
        d += timedelta(days=1)
    return out


def _apply_room(res: Reservation, room: dict, arrival: date, departure: date) -> None:
    occ = room.get("occupancy") or {}
    rt = res.room.room_type
    res.arrival, res.departure = arrival, departure
    res.adults = max(1, min(int(occ.get("adults") or 1), rt.max_adults))
    res.children = min(int(occ.get("children") or 0) + int(occ.get("infants") or 0), rt.max_children)
    nightly = _nightly(room, arrival, departure)
    if nightly:
        total = sum(Decimal(x) for x in nightly)
        res.nightly_rates = nightly if len(set(nightly)) > 1 else []
        res.rate = (total / len(nightly)).quantize(Decimal("0.01")) if len(set(nightly)) > 1 else Decimal(nightly[0])
    elif room.get("amount"):
        res.nightly_rates = []
        res.rate = (Decimal(str(room["amount"])) / max(1, (departure - arrival).days)).quantize(Decimal("0.01"))


def process_revision(rev: dict) -> ChannelBooking:
    booking_id = rev.get("booking_id") or rev["id"]
    channel = rev.get("ota_name") or "Channex"
    customer = rev.get("customer") or {}
    cb, created = ChannelBooking.objects.get_or_create(booking_id=booking_id)
    if not created and cb.revision_id == rev["id"]:
        return cb  # this revision was already applied (e.g. by another process before the ack)
    cb.revision_id = rev["id"]
    cb.status = rev.get("status", "")
    cb.channel = channel[:60]
    cb.channel_code = (rev.get("ota_reservation_code") or "")[:80]
    cb.guest_name = f"{customer.get('name', '')} {customer.get('surname', '')}".strip()[:160]
    cb.arrival = date.fromisoformat(rev["arrival_date"]) if rev.get("arrival_date") else None
    cb.departure = date.fromisoformat(rev["departure_date"]) if rev.get("departure_date") else None
    cb.amount = Decimal(str(rev["amount"])) if rev.get("amount") not in (None, "") else None
    cb.currency = (rev.get("currency") or "")[:3]
    cb.payload = rev
    problems: list[str] = []
    existing = {r.external_uid: r for r in cb.reservations.select_related("room__room_type")}

    if cb.status == "cancelled":
        for res in existing.values():
            if res.status == Reservation.Status.BOOKED:
                with transaction.atomic():
                    services.cancel(res, None)
    else:
        guest = None
        notes = "\n".join(
            x
            for x in (
                _("%(channel)s booking %(code)s") % {"channel": channel, "code": cb.channel_code},
                _("Paid to the channel") if rev.get("payment_collect") == "ota" else "",
                rev.get("notes") or "",
            )
            if x
        )
        rooms = rev.get("rooms") or []
        for i, room in enumerate(rooms):
            uid = f"cx:{booking_id}:{i}"
            arrival = date.fromisoformat(room.get("checkin_date") or rev["arrival_date"])
            departure = date.fromisoformat(room.get("checkout_date") or rev["departure_date"])
            rt = RoomType.objects.filter(channex_room_type_id=room.get("room_type_id") or "-").first()
            if rt is None:
                problems.append(_("Room type %(id)s is not linked in InnKeeper.") % {"id": room.get("room_type_id")})
                continue
            res = existing.get(uid)
            try:
                with transaction.atomic():
                    if res is None:
                        guest = guest or _guest(customer, channel)
                        candidates = list(free_rooms(rt, arrival, departure)[:10])
                        if not candidates:
                            raise ValidationError(
                                _("No free %(type)s from %(a)s to %(b)s.")
                                % {
                                    "type": rt.name,
                                    "a": arrival.strftime("%d.%m.%Y"),
                                    "b": departure.strftime("%d.%m.%Y"),
                                }
                            )
                        res = Reservation(
                            guest=guest,
                            room=candidates[0],
                            source=_source(channel),
                            external_ref=cb.channel_code[:60],
                            external_uid=uid,
                            notes=notes,
                            rate=rt.base_rate,
                        )
                        _apply_room(res, room, arrival, departure)
                        services.save_reservation(res, None)
                    elif res.status == Reservation.Status.BOOKED:
                        if res.room.room_type_id != rt.pk or not _room_free(res, arrival, departure):
                            new_room = free_rooms(rt, arrival, departure).exclude(pk=res.room_id).first()
                            if new_room is None:
                                raise ValidationError(_("The changed dates don't fit any free room of this type."))
                            res.room = new_room
                        _apply_room(res, room, arrival, departure)
                        services.save_reservation(res, None)
            except (ValidationError, Exception) as e:  # keep going with the other rooms
                if not isinstance(e, ValidationError):
                    log.exception("Channel booking %s failed", booking_id)
                msg = " ".join(m for v in e.message_dict.values() for m in v) if hasattr(e, "message_dict") else str(e)
                problems.append(msg[:200])
        # Rooms that were removed from the booking
        for uid, res in existing.items():
            index = int(uid.rsplit(":", 1)[1])
            if index >= len(rooms) and res.status == Reservation.Status.BOOKED:
                with transaction.atomic():
                    services.cancel(res, None)
    cb.problem = " · ".join(problems)[:255]
    cb.save()
    audit(None, f"channel.booking_{cb.status}", f"{channel} {cb.channel_code} {cb.guest_name}", cb)
    return cb


def _room_free(res: Reservation, arrival: date, departure: date) -> bool:
    return not Reservation.objects.filter(
        ~Q(pk=res.pk),
        room_id=res.room_id,
        status__in=Reservation.ACTIVE_STATUSES,
        arrival__lt=departure,
        departure__gt=arrival,
    ).exists()


def pull() -> list[ChannelBooking]:
    """Read new booking revisions from Channex, apply them and acknowledge each one."""
    with _pull_lock:
        return _pull()


def _pull() -> list[ChannelBooking]:
    hs = HotelSettings.load()
    if not hs.channex_configured:
        return []
    client = Client.from_settings(hs)
    done = []
    for _page in range(10):
        revisions = client.feed(hs.channex_property_id)
        if not revisions:
            break
        for rev in revisions:
            done.append(process_revision(rev))
            client.ack(rev["id"])
        if len(revisions) < 10:
            break
    ChannelSyncState.objects.update_or_create(pk=1, defaults={"last_pull": timezone.now()})
    return done


def sync(force_push: bool = False) -> dict:
    """Pull bookings first (they change availability), then push. Used by the background job."""
    result = {"bookings": 0, "pushed": False, "error": ""}
    try:
        result["bookings"] = len(pull())
        result["pushed"] = push(force=force_push)
    except ChannexError as e:
        result["error"] = str(e)
        ChannelSyncState.objects.update_or_create(pk=1, defaults={"last_error": str(e)[:255]})
    return result
