"""
Fiscalization rules.

* A bill paid in a restaurant, bar or service outlet is fiscalized when it is closed (not when it is
  charged to a room: those charges are on the guest's bill).
* A guest bill is fiscalized when it is closed at check-out.
* Each document gets its ordinal number, NSLF (IIC) and signature immediately, so the receipt can be
  printed even without internet. If the tax authority can't be reached, the document is sent again
  automatically as a "subsequent delivery" (allowed within 48 hours); the NIVF is added when it arrives.
* Cash invoices need the day's opening cash reported first (RegisterCashDeposit INITIAL).
* A voided receipt gets a corrective invoice with negative amounts that refers to the original.
"""

import logging
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import HotelSettings, audit

from . import cis
from .models import CashDeposit, FiscalCounter, FiscalDocument
from .signing import Certificate, CertificateError, iic

log = logging.getLogger(__name__)
_offline_until = None  # after a failed connection, don't make every sale wait for the timeout
CENT = Decimal("0.01")
UNIT = "copë"


def enabled() -> bool:
    return HotelSettings.load().fiscal_configured


def _vat(hs, accommodation: bool = False) -> Decimal | None:
    if not hs.vat_rate:
        return None  # not registered for VAT
    return hs.vat_rate_accommodation if accommodation else hs.vat_rate


def _operator(hs, user) -> str:
    return (getattr(user, "fiscal_operator_code", "") or hs.fiscal_operator_code or "").strip()


def _seller(hs) -> dict:
    return {"nuis": hs.tax_id.strip(), "name": hs.legal_name or hs.name, "address": hs.address, "town": hs.fiscal_town}


def _payments(rows: list[tuple[str, Decimal]], total: Decimal) -> tuple[str, list[dict]]:
    """Fiscal payment lines that add up exactly to the total, and the invoice type (CASH/NONCASH)."""
    by_type: dict[str, Decimal] = {}
    for method, amount in rows:
        t = cis.PAY_TYPES.get(method, "OTHER")
        by_type[t] = by_type.get(t, Decimal("0")) + amount
    by_type = {k: v for k, v in by_type.items() if v > 0}
    paid = sum(by_type.values(), Decimal("0"))
    if paid < total:
        by_type["ACCOUNT"] = by_type.get("ACCOUNT", Decimal("0")) + (total - paid)  # unpaid: on account
    elif paid > total and by_type:
        biggest = max(by_type, key=by_type.get)
        by_type[biggest] -= paid - total
    kind = "CASH" if by_type and all(k in cis.CASH_TYPES for k in by_type) else "NONCASH"
    return kind, [{"type": k, "amount": str(v.quantize(CENT))} for k, v in by_type.items() if v > 0] or [
        {"type": "BANKNOTE", "amount": "0.00"}
    ]


def _make_exact(lines: list[dict], target: Decimal) -> None:
    """Rounding after a discount can leave a cent or two: put it on a single unit, so the fiscal
    total is exactly what was paid (otherwise a cash sale could turn into NONCASH)."""
    total = sum(Decimal(x["unit_price"]) * Decimal(x["quantity"]) for x in lines).quantize(CENT)
    diff = target - total
    if not diff or not lines:
        return
    for x in lines:
        if Decimal(x["quantity"]) == 1 and Decimal(x["unit_price"]) + diff >= 0:
            x["unit_price"] = str((Decimal(x["unit_price"]) + diff).quantize(CENT))
            return
    # No single-unit line: take one unit off the largest line into a line of its own.
    for x in sorted(lines, key=lambda x: Decimal(x["unit_price"]) * Decimal(x["quantity"]), reverse=True):
        q, price = Decimal(x["quantity"]), Decimal(x["unit_price"])
        if q > 1 and q == q.to_integral_value() and price + diff >= 0:
            x["quantity"] = str(q - 1)
            lines.insert(lines.index(x) + 1, {**x, "quantity": "1", "unit_price": str((price + diff).quantize(CENT))})
            return


_CONTROL = dict.fromkeys(range(32), " ")


def _clean_text(value: str) -> str:
    """Names from imports or channels may contain tabs, line breaks or control characters XML can't carry."""
    return " ".join(str(value).translate(_CONTROL).split())


@transaction.atomic
def create_document(
    *,
    kind: str,
    lines: list[dict],
    payments: list[tuple[str, Decimal]],
    tcr: str,
    user,
    order=None,
    folio=None,
    corrects: FiscalDocument | None = None,
    total: Decimal | None = None,
) -> FiscalDocument:
    hs = HotelSettings.load()
    cert = Certificate.from_settings(hs)
    for x in lines:
        x["name"] = _clean_text(x["name"]) or "-"
    calc = cis.totals(
        [
            cis.Line(
                x["name"],
                x.get("code", ""),
                x["unit"],
                Decimal(x["quantity"]),
                Decimal(x["unit_price"]),
                Decimal(x["vat_rate"]) if x.get("vat_rate") is not None else None,
            )
            for x in lines
        ]
    )
    total = calc["total"].quantize(CENT) if total is None else total
    inv_type, pay = _payments(payments, abs(total))
    if total < 0:  # a correction refunds the same way it was paid
        inv_type = corrects.type_of_inv if corrects else inv_type
        pay = [
            {"type": p["type"], "amount": str(-Decimal(p["amount"]))}
            for p in (corrects.payload["payments"] if corrects else pay)
        ]
    issued = cis.now_str()
    year = int(issued[:4])
    ord_num = FiscalCounter.next(tcr, year)
    operator = _operator(hs, user)
    nuis = hs.tax_id.strip()
    code, signature = iic(
        cert, [nuis, issued, str(ord_num), hs.fiscal_business_unit, tcr, hs.fiscal_software_code, cis.money(total)]
    )
    payload = {
        "nuis": nuis,
        "in_vat": bool(hs.vat_rate),
        "currency": hs.currency,
        "ex_rate": str(hs.fiscal_exchange_rate) if hs.fiscal_exchange_rate else None,
        "seller": _seller(hs),
        "lines": lines,
        "payments": pay,
        "invoice": {
            "type": inv_type,
            "issue_datetime": issued,
            "inv_num": f"{ord_num}/{year}/{tcr}",
            "inv_ord_num": ord_num,
            "tcr": tcr,
            "operator": operator,
            "business_unit": hs.fiscal_business_unit,
            "software": hs.fiscal_software_code,
            "iic": code,
            "iic_signature": signature,
            "corrects": {"iic": corrects.iic, "issue_datetime": corrects.issue_datetime} if corrects else None,
        },
    }
    doc = FiscalDocument.objects.create(
        kind=kind,
        order=order,
        folio=folio,
        corrects=corrects,
        type_of_inv=inv_type,
        tcr_code=tcr,
        business_unit=hs.fiscal_business_unit,
        operator_code=operator,
        software_code=hs.fiscal_software_code,
        inv_ord_num=ord_num,
        inv_num=payload["invoice"]["inv_num"],
        issue_datetime=issued,
        total=total,
        iic=code,
        iic_signature=signature,
        test=hs.fiscal_test,
        payload=payload,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    audit(user, "fiscal.issue", f"{doc.inv_num} {doc.total} NSLF {doc.iic}", doc)
    return doc


def transmit(doc: FiscalDocument) -> FiscalDocument:
    """Send a document to the tax authority. Never raises: the result is in doc.status / doc.last_error."""
    if doc.status == FiscalDocument.Status.REGISTERED:
        return doc
    global _offline_until
    hs = HotelSettings.load()
    try:
        if _offline_until and timezone.now() < _offline_until and not doc.was_offline:
            raise cis.CISUnavailable(_("offline"))
        cert = Certificate.from_settings(hs)
        if doc.type_of_inv == "CASH":
            ensure_initial_deposit(doc.tcr_code, None, cert=cert)
        late = doc.created_at and timezone.now() - doc.created_at > timedelta(minutes=2)
        subsequent = "NOINTERNET" if doc.was_offline else ("TECHNICALERROR" if late else "")
        xml = cis.invoice_request(doc.payload, cert, subsequent=subsequent)
        fic = cis.register_invoice(xml, test=doc.test)
    except cis.CISUnavailable as e:
        if str(e) != _("offline"):
            _offline_until = timezone.now() + timedelta(seconds=60)
        doc.was_offline = True
        doc.last_error = _("No connection to the tax authority (%(e)s). It will be sent automatically.") % {"e": e}
    except (cis.CISError, CertificateError) as e:
        doc.status = FiscalDocument.Status.FAILED
        doc.last_error = f"{getattr(e, 'code', '')} {e}".strip()
        log.warning("Fiscal document %s rejected: %s", doc.inv_num, doc.last_error)
    except Exception as e:  # anything else (bad data, unexpected reply): one document must never block the queue
        doc.status = FiscalDocument.Status.FAILED
        doc.last_error = f"{type(e).__name__}: {e}"[:500]
        log.exception("Fiscal document %s could not be sent", doc.inv_num)
    else:
        _offline_until = None
        doc.status, doc.fic, doc.last_error, doc.registered_at = (
            FiscalDocument.Status.REGISTERED,
            fic,
            "",
            timezone.now(),
        )
    doc.attempts += 1
    doc.save(update_fields=["status", "fic", "last_error", "registered_at", "was_offline", "attempts"])
    return doc


def resend_pending() -> int:
    """Send documents that are still waiting (no internet earlier), and fiscalize any sale that
    couldn't get a document at all (e.g. the certificate was missing). Run every minute."""
    if not enabled():
        return 0
    n = 0
    # Documents a sale is sending right now are left to it, so nothing is sent twice.
    recent = timezone.now() - timedelta(minutes=2)
    waiting = FiscalDocument.objects.filter(status=FiscalDocument.Status.PENDING).exclude(
        was_offline=False, created_at__gt=recent
    )
    for doc in waiting.order_by("created_at")[:50]:
        doc = transmit(doc)
        if doc.status == FiscalDocument.Status.REGISTERED:
            n += 1
        elif doc.status == FiscalDocument.Status.PENDING:
            break  # still no connection: try the rest next time
    for kind, obj in unfiscalized(limit=20):
        safely(fiscalize_order if kind == "order" else fiscalize_folio, obj, None)
    return n


def unfiscalized(limit: int = 100) -> list[tuple[str, object]]:
    """Paid bills and closed guest bills since fiscalization was turned on that have no document."""
    from django.db.models import Q

    from apps.finance.models import Folio
    from apps.outlets.models import Order

    hs = HotelSettings.load()
    if not hs.fiscal_since:
        return []
    since = max(hs.fiscal_since, timezone.now() - timedelta(days=3))
    settled = timezone.now() - timedelta(minutes=2)  # leave a sale a moment to fiscalize itself
    found: list[tuple[str, object]] = []
    orders = (
        Order.objects.filter(status=Order.Status.CLOSED, closed_at__gte=since, closed_at__lt=settled)
        .filter(Q(settlement=Order.Settlement.PAID) | Q(settlement=Order.Settlement.ROOM, payments__voided=False))
        .filter(fiscal_documents__isnull=True)
        .distinct()
        .select_related("outlet")
    )
    for o in orders[:limit]:
        if _order_target(o) > 0:
            found.append(("order", o))
    folios = Folio.objects.filter(
        status=Folio.Status.CLOSED, closed_at__gte=since, closed_at__lt=settled, fiscal_documents__isnull=True
    )
    for f in folios[:limit]:
        if f.total_charges > 0:
            found.append(("folio", f))
    return found[:limit]


def overdue() -> int:
    """Documents still not registered after 40 hours (the law allows 48)."""
    return FiscalDocument.objects.filter(
        status__in=[FiscalDocument.Status.PENDING, FiscalDocument.Status.FAILED],
        created_at__lt=timezone.now() - timedelta(hours=40),
    ).count()


# ---------- Cash deposits ----------


def ensure_initial_deposit(
    tcr: str, user, *, cert: Certificate | None = None, amount: Decimal | None = None
) -> CashDeposit:
    today = timezone.localdate()
    existing = CashDeposit.objects.filter(
        business_date=today,
        tcr_code=tcr,
        operation=CashDeposit.Operation.INITIAL,
        status="registered",
        test=HotelSettings.load().fiscal_test,  # a test-system report doesn't count once live
    ).first()
    if existing:
        return existing
    if amount is None:
        from apps.finance.models import DayClose

        last = DayClose.objects.filter(business_date__lt=today).order_by("-business_date").first()
        amount = last.counted_cash if last else Decimal("0.00")
    return register_cash(tcr, CashDeposit.Operation.INITIAL, amount, user, cert=cert, raise_unavailable=True)


def register_cash(
    tcr: str, operation: str, amount: Decimal, user, *, cert=None, raise_unavailable=False
) -> CashDeposit:
    hs = HotelSettings.load()
    cert = cert or Certificate.from_settings(hs)
    when = cis.now_str()
    amount = Decimal(amount)
    if (hs.currency or "ALL").upper() != "ALL" and hs.fiscal_exchange_rate:
        amount = amount * hs.fiscal_exchange_rate  # cash in the drawer is reported in lekë
    dep = CashDeposit.objects.create(
        business_date=timezone.localdate(),
        tcr_code=tcr,
        operation=operation,
        amount=amount.quantize(CENT, ROUND_HALF_UP),
        change_datetime=when,
        test=hs.fiscal_test,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    xml = cis.cash_deposit_request(
        nuis=hs.tax_id.strip(), tcr=tcr, operation=operation, amount=dep.amount, when=when, cert=cert
    )
    try:
        dep.fcdc = cis.register_cash_deposit(xml, test=hs.fiscal_test)
        dep.status = "registered"
    except cis.CISUnavailable as e:
        dep.status, dep.last_error = "failed", str(e)
        dep.save()
        if raise_unavailable:
            raise
        return dep
    except cis.CISError as e:
        dep.status, dep.last_error = "failed", f"{e.code} {e}".strip()
    dep.save()
    audit(user, "fiscal.cash", f"{tcr} {operation} {dep.amount} {dep.status}", dep)
    return dep


# ---------- From InnKeeper's bills ----------


def tcr_for_outlet(outlet) -> str:
    return (getattr(outlet, "fiscal_tcr_code", "") or HotelSettings.load().fiscal_tcr_code).strip()


def _order_target(order) -> Decimal:
    """What a restaurant/bar bill's receipt is for: all of it when paid, or the part paid at the table
    when the rest went to a room (that rest is on the guest's bill and its invoice)."""
    from apps.outlets.models import Order

    if order.settlement == Order.Settlement.ROOM:
        return order.paid
    return order.total


def fiscalize_order(order, user) -> FiscalDocument | None:
    """A paid restaurant/bar/service bill (or the paid part of one charged to a room)."""
    if not enabled() or order.fiscal_documents.exists():
        return None
    hs = HotelSettings.load()
    lines_qs = list(order.active_lines)
    target = _order_target(order)
    if not lines_qs or target <= 0:
        return None  # nothing paid (e.g. fully discounted)
    factor = (target / order.subtotal) if order.subtotal else Decimal("1")
    vat = _vat(hs)
    lines = [
        {
            "name": ln.name,
            "code": str(ln.item_id or ""),
            "unit": UNIT,
            "quantity": str(ln.quantity),
            "unit_price": str((ln.unit_price * factor).quantize(CENT, ROUND_HALF_UP)),
            "vat_rate": str(vat) if vat is not None else None,
        }
        for ln in lines_qs
    ]
    _make_exact(lines, target)
    payments = [(p.method, p.amount) for p in order.payments.filter(voided=False)]
    doc = create_document(
        kind=FiscalDocument.Kind.RECEIPT,
        lines=lines,
        payments=payments,
        tcr=tcr_for_outlet(order.outlet),
        user=user,
        order=order,
    )
    return transmit(doc)


def fiscalize_folio(folio, user) -> FiscalDocument | None:
    """A guest bill, at check-out: room nights at the accommodation VAT rate, everything else at the main rate."""
    if not enabled() or folio.fiscal_documents.exists():
        return None
    hs = HotelSettings.load()
    from apps.finance.models import Charge

    charges = list(folio.charges.filter(voided=False).order_by("business_date", "id"))
    if not charges or sum(c.amount for c in charges) <= 0:
        return None
    lines = []
    for c in charges:
        vat = _vat(hs, accommodation=c.kind == Charge.Kind.ACCOMMODATION)
        lines.append(
            {
                "name": c.description,
                "code": c.kind,
                "unit": _("night") if c.kind == Charge.Kind.ACCOMMODATION else UNIT,
                "quantity": str(c.quantity),
                "unit_price": str(c.unit_price),
                "vat_rate": str(vat) if vat is not None else None,
            }
        )
    payments = [(p.method, p.amount) for p in folio.payments.filter(voided=False)]
    doc = create_document(
        kind=FiscalDocument.Kind.INVOICE,
        lines=lines,
        payments=payments,
        tcr=hs.fiscal_tcr_code.strip(),
        user=user,
        folio=folio,
    )
    return transmit(doc)


def correct_order(order, user) -> FiscalDocument | None:
    """A voided receipt: corrective invoice with the same lines, negative, pointing at the original."""
    original = order.fiscal_documents.filter(kind=FiscalDocument.Kind.RECEIPT).first()
    if not enabled() or original is None or original.corrections.exists():
        return None
    lines = [{**x, "quantity": str(-Decimal(x["quantity"]))} for x in original.payload["lines"]]
    doc = create_document(
        kind=FiscalDocument.Kind.CORRECTION,
        lines=lines,
        payments=[],
        tcr=original.tcr_code,
        user=user,
        order=order,
        corrects=original,
        total=-original.total,
    )
    return transmit(doc)


def safely(fn, *args) -> None:
    """Fiscalization must never stop a sale: log problems, the document list shows them."""
    try:
        fn(*args)
    except Exception:
        log.exception("Fiscalization failed")
