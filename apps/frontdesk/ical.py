"""
Calendar sync with Booking.com, Airbnb, Expedia and others, using the iCal links every channel offers.

* **Export:** each room has a secret link (`room_calendar_url`) that lists when it is taken.
  Paste it into the channel's calendar import so rooms booked here are closed there.
* **Import:** paste the channel's export link into InnKeeper (`CalendarFeed`). Its bookings become
  reservations here, so the room can't be sold twice. Bookings that disappear from the channel's
  calendar (cancelled there) are cancelled here, and changed dates are updated.

iCal carries only dates, not guest names or prices: reception completes those when the guest arrives.
"""

import logging
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import HotelSettings, audit

from . import services
from .models import CalendarFeed, Guest, Reservation, Room
from .pricing import apply_quote, quote

log = logging.getLogger(__name__)
SALT = "innkeeper.room-calendar"
MAX_BYTES = 5 * 1024 * 1024


# ---------- Export ----------


def room_token(room: Room) -> str:
    return signing.Signer(salt=SALT).sign(str(room.pk)).replace(":", "-")


def room_from_token(token: str) -> Room | None:
    try:
        pk = signing.Signer(salt=SALT).unsign(token.replace("-", ":", 1))
    except signing.BadSignature:
        return None
    return Room.objects.filter(pk=pk).first()


def room_calendar_url(room: Room, base_url: str = "") -> str:
    base = (HotelSettings.load().public_url or base_url).rstrip("/")
    return f"{base}{reverse('ical_room', args=[room_token(room)])}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """iCal lines are at most 75 octets; longer ones continue on the next line after a space."""
    out, raw = [], line.encode("utf-8")
    while len(raw) > 75:
        cut = 75
        while (raw[cut] & 0xC0) == 0x80:  # don't split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    out.append(raw.decode("utf-8"))
    return "\r\n".join(out)


def export_room(room: Room) -> str:
    hs = HotelSettings.load()
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//InnKeeper//Room calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(f'{hs.name} – {room.number}')}",
    ]
    since = timezone.localdate() - timedelta(days=30)
    for r in room.reservations.filter(status__in=Reservation.ACTIVE_STATUSES, departure__gte=since):
        lines += [
            "BEGIN:VEVENT",
            f"UID:{r.code}-{r.pk}@innkeeper",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{r.arrival:%Y%m%d}",
            f"DTEND;VALUE=DATE:{r.departure:%Y%m%d}",
            "SUMMARY:" + _escape(_("Not available")),  # never guest names: these links can be seen by the channel
            "STATUS:CONFIRMED",
            "TRANSP:OPAQUE",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


# ---------- Import ----------


@dataclass
class Event:
    uid: str
    start: date
    end: date
    summary: str = ""
    cancelled: bool = False


def _parse_date(value: str) -> date | None:
    value = value.strip()
    try:
        if "T" in value:
            if value.endswith("Z"):
                dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
                return timezone.localtime(dt).date()
            return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").date()
        return datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _unescape(text: str) -> str:
    return text.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def parse(text: str) -> list[Event]:
    if "BEGIN:VCALENDAR" not in text:
        raise ValueError(_("This link doesn't return a calendar (iCal)."))
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    events, cur = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            start = _parse_date(cur.get("DTSTART", ""))
            end = _parse_date(cur.get("DTEND", "")) if cur.get("DTEND") else None
            if start:
                end = end if end and end > start else start + timedelta(days=1)
                uid = cur.get("UID") or f"{start:%Y%m%d}-{end:%Y%m%d}"
                events.append(
                    Event(
                        uid=uid[:255],
                        start=start,
                        end=end,
                        summary=_unescape(cur.get("SUMMARY", ""))[:200],
                        cancelled=cur.get("STATUS", "").upper() == "CANCELLED",
                    )
                )
            cur = None
        elif cur is not None and ":" in line:
            name, value = line.split(":", 1)
            cur[name.split(";", 1)[0].upper()] = value
    return events


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "InnKeeper calendar sync"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310  (links are entered by managers)
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(_("The calendar is too large."))
    return data.decode("utf-8", errors="replace")


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    cancelled: int = 0
    conflicts: list | None = None
    error: str = ""


def _conflict(event: Event, reason) -> dict:
    if isinstance(reason, ValidationError):
        reason = " ".join(m for msgs in reason.message_dict.values() for m in msgs)
    return {
        "start": event.start.isoformat(),
        "end": event.end.isoformat(),
        "summary": event.summary,
        "reason": str(reason),
    }


def sync_feed(feed: CalendarFeed) -> SyncResult:
    result = SyncResult(conflicts=[])
    try:
        events = parse(fetch(feed.url))
    except Exception as e:  # network errors, bad links, not a calendar
        result.error = str(getattr(e, "reason", None) or e)[:255]
        feed.last_error = result.error
        feed.last_sync = timezone.now()
        feed.save(update_fields=["last_error", "last_sync"])
        log.warning("Calendar %s failed: %s", feed, result.error)
        return result

    today = timezone.localdate()
    live = {e.uid: e for e in events if not e.cancelled and e.end > today}
    existing = {r.external_uid: r for r in feed.reservations.all()}
    channel = feed.get_source_display()

    for uid, ev in live.items():
        res = existing.get(uid)
        try:
            with transaction.atomic():
                if res is None:
                    guest = Guest.objects.create(first_name=channel, last_name=_("guest"))
                    res = Reservation(
                        guest=guest,
                        room=feed.room,
                        arrival=ev.start,
                        departure=ev.end,
                        adults=1,
                        source=feed.source,
                        feed=feed,
                        external_uid=uid,
                        notes=_("From the %(channel)s calendar. Add the guest's details and check the price.")
                        % {"channel": channel}
                        + (f"\n{ev.summary}" if ev.summary else ""),
                    )
                    apply_quote(res, quote(feed.room.room_type, ev.start, ev.end))
                    services.save_reservation(res, None)
                    result.created += 1
                elif res.status == Reservation.Status.BOOKED and (res.arrival, res.departure) != (ev.start, ev.end):
                    res.arrival, res.departure = ev.start, ev.end
                    apply_quote(res, quote(feed.room.room_type, ev.start, ev.end))
                    services.save_reservation(res, None)
                    result.updated += 1
        except ValidationError as e:
            result.conflicts.append(_conflict(ev, e))

    for uid, res in existing.items():
        if uid not in live and res.status == Reservation.Status.BOOKED and res.departure > today:
            with transaction.atomic():
                services.cancel(res, None)
            Reservation.objects.filter(pk=res.pk).update(
                notes=(res.notes + "\n" + _("Cancelled on %(channel)s.") % {"channel": channel}).strip()
            )
            result.cancelled += 1

    feed.last_sync = timezone.now()
    feed.last_error = ""
    feed.conflicts = result.conflicts
    feed.save(update_fields=["last_sync", "last_error", "conflicts"])
    if result.created or result.updated or result.cancelled:
        audit(
            None,
            "calendar.sync",
            f"{feed}: +{result.created} ~{result.updated} -{result.cancelled}",
            feed,
        )
    return result


def sync_all() -> dict[CalendarFeed, SyncResult]:
    return {feed: sync_feed(feed) for feed in CalendarFeed.objects.filter(is_active=True).select_related("room")}
