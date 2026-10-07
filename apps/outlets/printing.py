"""
Printing to thermal receipt printers (ESC/POS, the standard for 58/80 mm printers).

Two ways to reach a printer:
* **Network** – raw TCP to the printer's IP address, port 9100. Works from any server on the same network.
* **Installed on this computer** – through the operating system's printer queue in RAW mode
  (Windows: win32print; Linux/macOS: `lp -o raw`). Use this for USB printers on the PC running InnKeeper.

Every job is stored, so a job that fails (printer off, out of paper) can be retried later.
"""

import socket
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext as _

from .models import PrintJob, Printer

ESC, GS = b"\x1b", b"\x1d"
CODEPAGE_WPC1252 = 16  # Epson-compatible number for Windows-1252, which covers ë, ç, €.


class Receipt:
    """Small ESC/POS document builder."""

    def __init__(self, width_mm: int = 80):
        self.cols = 48 if width_mm >= 80 else 32
        self.buf = bytearray(ESC + b"@" + ESC + b"t" + bytes([CODEPAGE_WPC1252]))

    # --- text -------------------------------------------------------------
    def _enc(self, text: str) -> bytes:
        return str(text).encode("cp1252", errors="replace")

    def text(self, text: str = "", *, bold=False, big=False, tall=False, align="left") -> "Receipt":
        self.buf += ESC + b"a" + bytes([{"left": 0, "center": 1, "right": 2}[align]])
        if bold:
            self.buf += ESC + b"E\x01"
        if big or tall:
            self.buf += GS + b"!" + bytes([0x11 if big else 0x01])
        self.buf += self._enc(text) + b"\n"
        if big or tall:
            self.buf += GS + b"!\x00"
        if bold:
            self.buf += ESC + b"E\x00"
        if align != "left":
            self.buf += ESC + b"a\x00"
        return self

    def wrap(self, text: str, **kw) -> "Receipt":
        cols = self.cols // 2 if kw.get("big") else self.cols
        for paragraph in str(text).splitlines() or [""]:
            line = ""
            for word in paragraph.split(" "):
                if len(line) + len(word) + (1 if line else 0) > cols:
                    self.text(line, **kw)
                    line = word[:cols]
                else:
                    line = f"{line} {word}" if line else word
            self.text(line, **kw)
        return self

    def pair(self, left: str, right: str, *, bold=False, big=False) -> "Receipt":
        cols = self.cols // 2 if big else self.cols
        left, right = str(left), str(right)
        space = cols - len(right) - 1
        if len(left) > space:
            self.text(left, bold=bold, big=big)
            left = ""
        return self.text(left.ljust(space) + " " + right, bold=bold, big=big)

    def rule(self, char: str = "-") -> "Receipt":
        return self.text(char * self.cols)

    def feed(self, lines: int = 1) -> "Receipt":
        self.buf += b"\n" * lines
        return self

    def qr(self, data: str, size: int = 5) -> "Receipt":
        """Print a QR code (ESC/POS GS ( k: model 2, error correction M), centered."""
        raw = data.encode("ascii", errors="replace")
        n = len(raw) + 3
        self.buf += ESC + b"a\x01"
        self.buf += GS + b"(k\x04\x001A2\x00"  # model 2
        self.buf += GS + b"(k\x03\x001C" + bytes([size])  # module size
        self.buf += GS + b"(k\x03\x001E1"  # error correction M
        self.buf += GS + b"(k" + bytes([n % 256, n // 256]) + b"1P0" + raw  # store
        self.buf += GS + b"(k\x03\x001Q0\n"  # print
        self.buf += ESC + b"a\x00"
        return self

    # --- hardware ---------------------------------------------------------
    def open_drawer(self) -> "Receipt":
        self.buf += ESC + b"p\x00\x19\xfa"
        return self

    def cut(self) -> "Receipt":
        self.buf += b"\n" * 4 + GS + b"V\x42\x00"
        return self

    def to_bytes(self) -> bytes:
        return bytes(self.buf)


def money(value, symbol: str) -> str:
    return f"{Decimal(value):.2f} {symbol}".strip()


# ---------- Sending ----------


class PrintError(Exception):
    pass


def _send_network(printer: Printer, data: bytes) -> None:
    if not printer.address:
        raise PrintError(_("No IP address set."))
    try:
        with socket.create_connection((printer.address, printer.port), timeout=4) as s:
            s.settimeout(6)
            s.sendall(data)
    except OSError as e:
        raise PrintError(
            _("Could not reach the printer at %(where)s (%(error)s).") % {"where": printer.where, "error": e}
        )


def _send_system(printer: Printer, data: bytes) -> None:
    name = printer.system_name.strip()
    if not name:
        raise PrintError(_("No printer name set."))
    if sys.platform.startswith("win"):
        try:
            import win32print  # type: ignore
        except ImportError:
            raise PrintError(_("Printing to installed printers needs the InnKeeper Windows app."))
        try:
            handle = win32print.OpenPrinter(name)
            try:
                win32print.StartDocPrinter(handle, 1, ("InnKeeper", None, "RAW"))
                win32print.StartPagePrinter(handle)
                win32print.WritePrinter(handle, data)
                win32print.EndPagePrinter(handle)
                win32print.EndDocPrinter(handle)
            finally:
                win32print.ClosePrinter(handle)
        except Exception as e:  # pywin32 raises its own error type
            raise PrintError(_("Windows could not print to “%(name)s” (%(error)s).") % {"name": name, "error": e})
        return
    try:
        subprocess.run(["lp", "-d", name, "-o", "raw"], input=data, check=True, capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        raise PrintError(_("The system could not print to “%(name)s” (%(error)s).") % {"name": name, "error": e})


def send(printer: Printer, data: bytes) -> None:
    if not printer.is_active:
        raise PrintError(_("This printer is switched off in InnKeeper."))
    if printer.connection == Printer.Connection.SYSTEM:
        _send_system(printer, data)
    else:
        _send_network(printer, data)


def submit(printer: Printer, title: str, data: bytes, user=None) -> PrintJob:
    """Print now and keep a record. Never raises: check job.status."""
    job = PrintJob.objects.create(printer=printer, title=title[:120], data=data, created_by=user)
    run_job(job)
    PrintJob.objects.filter(created_at__lt=timezone.now() - timedelta(days=3)).delete()
    return job


def run_job(job: PrintJob) -> PrintJob:
    job.attempts += 1
    try:
        send(job.printer, bytes(job.data))
    except PrintError as e:
        job.status, job.error = PrintJob.Status.FAILED, str(e)[:255]
    else:
        job.status, job.error = PrintJob.Status.DONE, ""
    job.save(update_fields=["attempts", "status", "error"])
    return job


# ---------- Documents ----------


def receipt_document(order, printer: Printer, *, open_drawer: bool = False) -> bytes:
    from apps.core.models import HotelSettings

    hs = HotelSettings.load()
    sym = hs.currency_symbol
    r = Receipt(printer.paper_width)
    r.wrap(hs.legal_name or hs.name, bold=True, align="center")
    for line in (order.outlet.name, hs.address, hs.phone, f"NIPT {hs.tax_id}" if hs.tax_id else ""):
        if line:
            r.wrap(line, align="center")
    if hs.receipt_header:
        r.wrap(hs.receipt_header, align="center")
    r.rule()
    closed = order.status != order.Status.OPEN
    r.pair(_("Receipt") if closed else _("Bill"), order.receipt_number or order.number)
    r.pair(order.display_name, timezone.localtime(order.closed_at or order.opened_at).strftime("%d.%m.%Y %H:%M"))
    if order.opened_by:
        r.pair(_("Served by"), str(order.opened_by))
    r.rule()
    for line in order.active_lines:
        r.pair(f"{line.quantity} x {line.name}", money(line.line_total, sym))
        if line.quantity > 1:
            r.text(f"   @ {money(line.unit_price, sym)}")
    r.rule()
    if order.discount:
        r.pair(_("Subtotal"), money(order.subtotal, sym))
        r.pair(_("Discount"), "-" + money(order.discount, sym))
    total = order.total
    r.pair(_("TOTAL"), money(total, sym), bold=True, big=printer.paper_width >= 80)
    if hs.receipt_show_vat and hs.vat_rate:
        vat = (total * hs.vat_fraction).quantize(Decimal("0.01"))
        r.pair(_("Without VAT"), money(total - vat, sym))
        r.pair(_("VAT %(r)s%%") % {"r": f"{hs.vat_rate:g}"}, money(vat, sym))
    r.rule()
    if order.status == order.Status.OPEN:
        r.text(_("Bill — not yet paid"), bold=True, align="center")
    elif order.status == order.Status.CANCELLED:
        r.text(_("VOID"), big=True, align="center")
    else:
        for p in order.payments.filter(voided=False):
            r.pair(p.get_method_display(), money(p.amount, sym))
            if p.tendered:
                r.pair(_("Cash given"), money(p.tendered, sym))
                r.pair(_("Change"), money(p.change, sym))
        room = (
            order.charges.filter(folio__isnull=False, voided=False).select_related("folio__reservation__room").first()
        )
        if room:
            r.pair(_("Charged to room") + f" {room.folio.reservation.room.number}", money(room.amount, sym))
            r.feed().text(_("Signature") + ": ____________________")
    if hs.receipt_footer:
        r.rule().wrap(hs.receipt_footer, align="center")
    fdoc = order.fiscal_documents.order_by("created_at").first()
    if fdoc:
        r.rule()
        r.qr(fdoc.verify_url, size=4 if printer.paper_width < 80 else 5)
        r.text(_("Invoice no.") + f" {fdoc.inv_num}", align="center")
        r.text(f"NSLF: {fdoc.iic}", align="center")
        r.text("NIVF: " + (fdoc.fic or _("will be added when the connection returns")), align="center")
        r.text(_("Operator") + f": {fdoc.operator_code}  TCR: {fdoc.tcr_code}", align="center")
        if fdoc.test:
            r.text(_("TEST – not valid for tax"), bold=True, align="center")
    else:
        r.text(_("This is not a fiscal receipt."), align="center")
    if open_drawer and printer.open_drawer:
        r.open_drawer()
    return r.cut().to_bytes()


def kitchen_document(ticket, printer: Printer) -> bytes:
    order = ticket.order
    r = Receipt(printer.paper_width)
    r.text(ticket.station.name.upper(), bold=True, align="center")
    r.text(order.display_name, big=True, align="center")
    r.text(
        f"#{order.number} · {timezone.localtime(ticket.sent_at):%H:%M} · {ticket.sent_by or ''}".strip(" ·"),
        align="center",
    )
    if order.guests > 1:
        r.text(_("Guests") + f": {order.guests}", align="center")
    r.rule("=")
    for line in ticket.lines.all():
        r.wrap(f"{line.quantity} x {line.name}", tall=True, bold=True)
        if line.note:
            r.wrap(f"   > {line.note}")
    if order.note:
        r.rule().wrap(_("Note") + f": {order.note}", bold=True)
    return r.cut().to_bytes()


def drawer_document() -> bytes:
    return ESC + b"@" + ESC + b"p\x00\x19\xfa"


def test_document(printer: Printer) -> bytes:
    from apps.core.models import HotelSettings

    r = Receipt(printer.paper_width)
    r.text("InnKeeper", big=True, align="center")
    r.text(HotelSettings.load().name, align="center")
    r.rule()
    r.text(_("Test print OK"), bold=True, align="center")
    r.text(f"{printer.name} · {printer.paper_width} mm", align="center")
    r.text(timezone.localtime().strftime("%d.%m.%Y %H:%M"), align="center")
    r.rule()
    r.text("ë ç Ë Ç € — Faleminderit!", align="center")
    r.pair("1 x Kafe", "1.50 €")
    if printer.open_drawer:
        r.open_drawer()
    return r.cut().to_bytes()
