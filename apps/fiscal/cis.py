"""
The tax authority's Fiscalization Service (CIS): building, signing and sending SOAP requests.

Schema: https://eFiskalizimi.tatime.gov.al/FiscalizationService/schema (version 3).
"""

import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone
from lxml import etree

from .signing import Certificate, sign_xml

log = logging.getLogger(__name__)

NS = "https://eFiskalizimi.tatime.gov.al/FiscalizationService/schema"
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
ACTION = "https://eFiskalizimi.tatime.gov.al/FiscalizationService/"
ENDPOINTS = {
    True: "https://efiskalizimi-test.tatime.gov.al/FiscalizationService-v3",
    False: "https://efiskalizimi.tatime.gov.al/FiscalizationService-v3",
}
VERIFY = {
    True: "https://efiskalizimi-app-test.tatime.gov.al/invoice-check/#/verify",
    False: "https://efiskalizimi-app.tatime.gov.al/invoice-check/#/verify",
}
CENT = Decimal("0.01")

# InnKeeper payment method → fiscal payment type (cash-type invoices use the first group).
PAY_TYPES = {"cash": "BANKNOTE", "card": "CARD", "online": "CARD", "bank_transfer": "ACCOUNT", "other": "OTHER"}
CASH_TYPES = {"BANKNOTE", "CARD", "CHECK", "SVOUCHER", "COMPANY", "ORDER"}


class CISError(Exception):
    """The service answered with an error (validation, certificate, …): sending again won't help."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


class CISUnavailable(Exception):
    """No answer (no internet, timeout, server down): send again later as a subsequent delivery."""


def now_str() -> str:
    return timezone.localtime().replace(microsecond=0).isoformat()


def money(v) -> str:
    return f"{Decimal(v).quantize(CENT, ROUND_HALF_UP):.2f}"


def quantity(q: Decimal) -> str:
    """Quantities need 2–10 decimals: 2 → "2.00", 0.25 → "0.25", 0.125 → "0.125"."""
    q = Decimal(q)
    return f"{q:.2f}" if q == q.quantize(CENT) else f"{q.normalize():f}"


def verify_url(doc) -> str:
    params = {
        "iic": doc.iic,
        "tin": doc.payload.get("nuis", ""),
        "crtd": doc.issue_datetime,
        "ord": doc.inv_ord_num,
        "bu": doc.business_unit,
        "cr": doc.tcr_code,
        "sw": doc.software_code,
        "prc": money(doc.total),
    }
    return f"{VERIFY[doc.test]}?{urllib.parse.urlencode(params)}"


# ---------- Building ----------


@dataclass
class Line:
    name: str
    code: str
    unit: str
    quantity: Decimal
    unit_price: Decimal  # with VAT
    vat_rate: Decimal | None  # None when the issuer is not in VAT

    def amounts(self) -> dict:
        pa = (self.unit_price * self.quantity).quantize(CENT, ROUND_HALF_UP)
        if self.vat_rate is None:
            return {"UPB": self.unit_price, "UPA": self.unit_price, "PB": pa, "PA": pa, "VA": None}
        factor = Decimal("1") + self.vat_rate / Decimal("100")
        pb = (pa / factor).quantize(CENT, ROUND_HALF_UP)
        upb = (self.unit_price / factor).quantize(CENT, ROUND_HALF_UP)
        return {"UPB": upb, "UPA": self.unit_price, "PB": pb, "PA": pa, "VA": pa - pb}


def totals(lines: list[Line]) -> dict:
    out = {"wo_vat": Decimal("0"), "vat": Decimal("0"), "total": Decimal("0"), "taxes": {}}
    for ln in lines:
        a = ln.amounts()
        out["wo_vat"] += a["PB"]
        out["total"] += a["PA"]
        if a["VA"] is not None:
            out["vat"] += a["VA"]
            t = out["taxes"].setdefault(ln.vat_rate, {"n": 0, "base": Decimal("0"), "vat": Decimal("0")})
            t["n"] += 1
            t["base"] += a["PB"]
            t["vat"] += a["VA"]
    return out


def invoice_request(payload: dict, cert: Certificate, *, subsequent: str = "") -> bytes:
    """Build and sign RegisterInvoiceRequest from a stored payload (see services.build_payload)."""
    root = etree.Element(f"{{{NS}}}RegisterInvoiceRequest", nsmap={None: NS}, Id="Request", Version="3")
    header = etree.SubElement(root, f"{{{NS}}}Header", UUID=str(uuid.uuid4()), SendDateTime=now_str())
    if subsequent:
        header.set("SubseqDelivType", subsequent)
    inv = payload["invoice"]
    lines = [
        Line(
            ln["name"],
            ln.get("code", ""),
            ln["unit"],
            Decimal(ln["quantity"]),
            Decimal(ln["unit_price"]),
            Decimal(ln["vat_rate"]) if ln.get("vat_rate") is not None else None,
        )
        for ln in payload["lines"]
    ]
    t = totals(lines)
    in_vat = payload["in_vat"]
    attrs = {
        "TypeOfInv": inv["type"],
        "IsSimplifiedInv": "false",
        "IssueDateTime": inv["issue_datetime"],
        "InvNum": inv["inv_num"],
        "InvOrdNum": str(inv["inv_ord_num"]),
        "TCRCode": inv["tcr"],
        "IsIssuerInVAT": "true" if in_vat else "false",
        "TotPriceWoVAT": money(t["wo_vat"]),
        "TotPrice": money(t["total"]),
        "OperatorCode": inv["operator"],
        "BusinUnitCode": inv["business_unit"],
        "SoftCode": inv["software"],
        "IIC": inv["iic"],
        "IICSignature": inv["iic_signature"],
        "IsReverseCharge": "false",
    }
    if in_vat:
        attrs["TotVATAmt"] = money(t["vat"])
    el = etree.SubElement(root, f"{{{NS}}}Invoice", **attrs)
    if inv.get("corrects"):
        c = inv["corrects"]
        etree.SubElement(
            el, f"{{{NS}}}CorrectiveInv", IICRef=c["iic"], IssueDateTime=c["issue_datetime"], Type="CORRECTIVE"
        )
    pay = etree.SubElement(el, f"{{{NS}}}PayMethods")
    for p in payload["payments"]:
        etree.SubElement(pay, f"{{{NS}}}PayMethod", Type=p["type"], Amt=money(p["amount"]))
    if payload.get("currency") and payload["currency"] != "ALL":
        etree.SubElement(el, f"{{{NS}}}Currency", Code=payload["currency"], ExRate=payload.get("ex_rate") or "1.00")
    seller = payload["seller"]
    etree.SubElement(
        el,
        f"{{{NS}}}Seller",
        IDType="NUIS",
        IDNum=seller["nuis"],
        Name=seller["name"][:100],
        Address=(seller.get("address") or "-")[:400],
        Town=(seller.get("town") or "-")[:100],
        Country="ALB",
    )
    if payload.get("buyer"):
        b = payload["buyer"]
        etree.SubElement(el, f"{{{NS}}}Buyer", **{k: v for k, v in b.items() if v})
    items = etree.SubElement(el, f"{{{NS}}}Items")
    for ln in lines:
        a = ln.amounts()
        i = {
            "N": ln.name[:50],
            "U": ln.unit[:50],
            "Q": quantity(ln.quantity),
            "UPB": money(a["UPB"]),
            "UPA": money(a["UPA"]),
            "PB": money(a["PB"]),
            "PA": money(a["PA"]),
        }
        if ln.code:
            i["C"] = ln.code[:50]
        if a["VA"] is not None:
            i["VR"] = money(ln.vat_rate)
            i["VA"] = money(a["VA"])
        etree.SubElement(items, f"{{{NS}}}I", **i)
    if in_vat and t["taxes"]:
        same = etree.SubElement(el, f"{{{NS}}}SameTaxes")
        for rate, v in sorted(t["taxes"].items()):
            etree.SubElement(
                same,
                f"{{{NS}}}SameTax",
                NumOfItems=str(v["n"]),
                PriceBefVAT=money(v["base"]),
                VATRate=money(rate),
                VATAmt=money(v["vat"]),
            )
    sign_xml(root, cert)
    return _envelope(root)


def cash_deposit_request(*, nuis: str, tcr: str, operation: str, amount, when: str, cert: Certificate) -> bytes:
    root = etree.Element(f"{{{NS}}}RegisterCashDepositRequest", nsmap={None: NS}, Id="Request", Version="3")
    etree.SubElement(root, f"{{{NS}}}Header", UUID=str(uuid.uuid4()), SendDateTime=now_str())
    etree.SubElement(
        root,
        f"{{{NS}}}CashDeposit",
        ChangeDateTime=when,
        Operation=operation,
        CashAmt=money(amount),
        TCRCode=tcr,
        IssuerNUIS=nuis,
    )
    sign_xml(root, cert)
    return _envelope(root)


def _envelope(root) -> bytes:
    env = etree.Element(f"{{{SOAP}}}Envelope", nsmap={"SOAP-ENV": SOAP})
    etree.SubElement(env, f"{{{SOAP}}}Header")
    body = etree.SubElement(env, f"{{{SOAP}}}Body")
    body.append(root)
    return etree.tostring(env, xml_declaration=True, encoding="UTF-8")


# ---------- Sending ----------


def send(xml: bytes, action: str, *, test: bool, timeout: int = 6) -> etree._Element:
    req = urllib.request.Request(ENDPOINTS[test], data=xml, method="POST")
    req.add_header("Content-Type", "text/xml; charset=utf-8")
    req.add_header("SOAPAction", f'"{ACTION}{action}"')
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raw = e.read()  # SOAP faults come with HTTP 500
        if not raw:
            raise CISUnavailable(f"HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CISUnavailable(str(getattr(e, "reason", e))) from e
    try:
        doc = etree.fromstring(raw)
    except etree.XMLSyntaxError as e:
        raise CISUnavailable("Unreadable answer from the tax authority") from e
    fault = doc.find(f".//{{{SOAP}}}Fault")
    if fault is not None:
        code = fault.findtext(".//code") or fault.findtext(".//{*}code") or fault.findtext("faultcode") or ""
        msg = fault.findtext("faultstring") or "Fault"
        raise CISError(msg.strip(), code.strip())
    return doc


def register_invoice(xml: bytes, *, test: bool) -> str:
    doc = send(xml, "RegisterInvoice", test=test)
    fic = doc.findtext(f".//{{{NS}}}FIC")
    if not fic:
        raise CISError("No NIVF (FIC) in the answer")
    return fic.strip()


def register_cash_deposit(xml: bytes, *, test: bool) -> str:
    doc = send(xml, "RegisterCashDeposit", test=test)
    return (doc.findtext(f".//{{{NS}}}FCDC") or "").strip()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)
