"""
The electronic invoice (e-faturë) as a UBL 2.1 invoice (European standard EN 16931), as the tax authority's
Einvoice Service expects it ("Einvoice Service - Technical specification", annex 6 and 7).

The invoice is built from the same stored payload as the fiscal invoice (services.create_document), after
the NIVF (FIC) came back: same number, lines, amounts and VAT, plus the fiscal codes as notes
("IIC=…#AAI#", "FIC=…#AAI#", …). It is signed with the business's certificate (enveloped XML signature
inside UBLExtensions, the same key that signs the request) and sent base64-encoded.
"""

import base64
import hashlib
from datetime import date, timedelta
from decimal import Decimal

from lxml import etree

from . import cis
from .signing import DS, ENVELOPED, EXC_C14N, RSA_SHA256, SHA256, Certificate, _c14n

INV = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
EXT = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
SIG = "urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2"
SAC = "urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2"
NSMAP = {None: INV, "cbc": CBC, "cac": CAC, "ext": EXT, "sig": SIG, "sac": SAC}

CUSTOMIZATION = "urn:cen.eu:en16931:2017"
PROFILE = "P1"
NUIS_SCHEME = "9923"  # electronic address scheme for Albanian NUIS
UNIT_PIECE = "H87"  # UN/ECE rec 20: piece
UNIT_NIGHT = "DAY"


def supported(payload: dict) -> bool:
    """E-invoices are sent for invoices in lekë. (How a foreign-currency e-invoice carries its exchange rate
    isn't in the published specification: those are issued in the self-care portal for now.)"""
    return (payload.get("currency") or "ALL").upper() == "ALL"


def _e(parent, ns, tag, text=None, **attrs):
    el = etree.SubElement(parent, f"{{{ns}}}{tag}", **attrs)
    if text is not None:
        el.text = str(text)
    return el


def _amount(parent, tag, value, currency):
    return _e(parent, CBC, tag, cis.money(value), currencyID=currency)


def _party(parent, wrapper, *, nuis, name, address, town, vat_id=None, tax_scheme=None):
    p = _e(_e(parent, CAC, wrapper), CAC, "Party")
    _e(p, CBC, "EndpointID", nuis, schemeID=NUIS_SCHEME)
    _e(_e(p, CAC, "PartyName"), CBC, "Name", name[:100])
    addr = _e(p, CAC, "PostalAddress")
    _e(addr, CBC, "StreetName", (address or "-")[:400])
    _e(addr, CBC, "CityName", (town or "-")[:100])
    _e(_e(addr, CAC, "Country"), CBC, "IdentificationCode", "AL")
    if vat_id:
        pts = _e(p, CAC, "PartyTaxScheme")
        _e(pts, CBC, "CompanyID", vat_id)
        _e(_e(pts, CAC, "TaxScheme"), CBC, "ID", tax_scheme)
    legal = _e(p, CAC, "PartyLegalEntity")
    _e(legal, CBC, "RegistrationName", name[:100])
    _e(legal, CBC, "CompanyID", nuis)
    return p


def _category(parent, tag, rate: Decimal | None):
    """VAT category: S (standard) or Z (0%) for a VAT payer; O (outside the scope of VAT) otherwise."""
    cat = _e(parent, CAC, tag)
    if rate is None:
        _e(cat, CBC, "ID", "O")
    else:
        _e(cat, CBC, "ID", "S" if rate > 0 else "Z")
        _e(cat, CBC, "Percent", cis.money(rate))
    return cat


def build(payload: dict, fic: str, *, iban: str = "", due_days: int = 15) -> etree._Element:
    """The (unsigned) UBL invoice for a registered fiscal invoice."""
    inv = payload["invoice"]
    currency = (payload.get("currency") or "ALL").upper()
    in_vat = bool(payload.get("in_vat"))
    issued = cis.parse_iso(inv["issue_datetime"])
    lines = [
        cis.Line(
            ln["name"],
            ln.get("code", ""),
            ln["unit"],
            Decimal(ln["quantity"]),
            Decimal(ln["unit_price"]),
            Decimal(ln["vat_rate"]) if ln.get("vat_rate") is not None else None,
        )
        for ln in payload["lines"]
    ]
    t = cis.totals(lines)

    root = etree.Element(f"{{{INV}}}Invoice", nsmap=NSMAP)
    # Room for the signature (filled in by sign()).
    content = _e(_e(_e(root, EXT, "UBLExtensions"), EXT, "UBLExtension"), EXT, "ExtensionContent")
    _e(_e(content, SIG, "UBLDocumentSignatures"), SAC, "SignatureInformation")
    _e(root, CBC, "CustomizationID", CUSTOMIZATION)
    _e(root, CBC, "ProfileID", PROFILE)
    _e(root, CBC, "ID", inv["inv_num"])
    _e(root, CBC, "IssueDate", issued.date().isoformat())
    _e(root, CBC, "DueDate", (issued.date() + timedelta(days=max(int(due_days or 0), 0))).isoformat())
    _e(root, CBC, "InvoiceTypeCode", "380")
    for key, value in (
        ("IIC", inv["iic"]),
        ("IICSignature", inv["iic_signature"]),
        ("FIC", fic),
        ("IssueDateTime", inv["issue_datetime"]),
        ("OperatorCode", inv["operator"]),
        ("BusinessUnitCode", inv["business_unit"]),
        ("SoftwareCode", inv["software"]),
        ("IsBadDebtInv", "false"),
    ):
        _e(root, CBC, "Note", f"{key}={value}#AAI#")
    _e(root, CBC, "DocumentCurrencyCode", currency)
    _e(root, CBC, "TaxCurrencyCode", currency)

    seller, buyer = payload["seller"], payload["buyer"]
    _party(
        root,
        "AccountingSupplierParty",
        nuis=seller["nuis"],
        name=seller["name"],
        address=seller.get("address"),
        town=seller.get("town"),
        vat_id=f"AL{seller['nuis']}" if in_vat else seller["nuis"],
        tax_scheme="VAT" if in_vat else "FRE",
    )
    _party(
        root,
        "AccountingCustomerParty",
        nuis=buyer["IDNum"],
        name=buyer["Name"],
        address=buyer.get("Address"),
        town=buyer.get("Town"),
    )

    # Paid (or to be paid) to the business's bank account; the NIVF links the payment to the invoice.
    means = _e(root, CAC, "PaymentMeans")
    iban = "".join((iban or "").split()).upper()
    _e(means, CBC, "PaymentMeansCode", "30" if iban else "42")
    _e(means, CBC, "PaymentID", fic)
    if iban:
        _e(_e(means, CAC, "PayeeFinancialAccount"), CBC, "ID", iban)

    tax_total = _e(root, CAC, "TaxTotal")
    _amount(tax_total, "TaxAmount", t["vat"] if in_vat else 0, currency)
    if in_vat and t["taxes"]:
        for rate, v in sorted(t["taxes"].items()):
            sub = _e(tax_total, CAC, "TaxSubtotal")
            _amount(sub, "TaxableAmount", v["base"], currency)
            _amount(sub, "TaxAmount", v["vat"], currency)
            _e(_category(sub, "TaxCategory", rate), CAC, "TaxScheme").append(_id("VAT"))
    else:
        sub = _e(tax_total, CAC, "TaxSubtotal")
        _amount(sub, "TaxableAmount", t["wo_vat"], currency)
        _amount(sub, "TaxAmount", 0, currency)
        cat = _category(sub, "TaxCategory", None)
        _e(cat, CBC, "TaxExemptionReasonCode", "vatex-eu-o")
        _e(cat, CAC, "TaxScheme").append(_id("VAT"))

    totals = _e(root, CAC, "LegalMonetaryTotal")
    _amount(totals, "LineExtensionAmount", t["wo_vat"], currency)
    _amount(totals, "TaxExclusiveAmount", t["wo_vat"], currency)
    _amount(totals, "TaxInclusiveAmount", t["total"], currency)
    _amount(totals, "PayableAmount", t["total"], currency)

    for n, ln in enumerate(lines, start=1):
        a = ln.amounts()
        row = _e(root, CAC, "InvoiceLine")
        _e(row, CBC, "ID", n)
        unit = UNIT_NIGHT if ln.code == "accommodation" else UNIT_PIECE
        _e(row, CBC, "InvoicedQuantity", cis.quantity(ln.quantity), unitCode=unit)
        _amount(row, "LineExtensionAmount", a["PB"], currency)
        item = _e(row, CAC, "Item")
        _e(item, CBC, "Name", ln.name[:100])
        if ln.code:
            _e(_e(item, CAC, "SellersItemIdentification"), CBC, "ID", ln.code[:50])
        _e(_category(item, "ClassifiedTaxCategory", ln.vat_rate), CAC, "TaxScheme").append(_id("VAT"))
        price = _e(row, CAC, "Price")
        _amount(price, "PriceAmount", a["UPB"], currency)
    return root


def _id(value):
    el = etree.Element(f"{{{CBC}}}ID")
    el.text = value
    return el


def sign(root, cert: Certificate) -> None:
    """Enveloped XML signature of the whole invoice, placed in UBLExtensions (Reference URI="")."""
    holder = root.find(f".//{{{SAC}}}SignatureInformation")
    digest = base64.b64encode(hashlib.sha256(_c14n(root)).digest()).decode()  # before the signature is added
    sig = etree.SubElement(holder, f"{{{DS}}}Signature", nsmap={"ds": DS})
    signed_info = etree.SubElement(sig, f"{{{DS}}}SignedInfo")
    etree.SubElement(signed_info, f"{{{DS}}}CanonicalizationMethod", Algorithm=EXC_C14N)
    etree.SubElement(signed_info, f"{{{DS}}}SignatureMethod", Algorithm=RSA_SHA256)
    ref = etree.SubElement(signed_info, f"{{{DS}}}Reference", URI="")
    transforms = etree.SubElement(ref, f"{{{DS}}}Transforms")
    etree.SubElement(transforms, f"{{{DS}}}Transform", Algorithm=ENVELOPED)
    etree.SubElement(transforms, f"{{{DS}}}Transform", Algorithm=EXC_C14N)
    etree.SubElement(ref, f"{{{DS}}}DigestMethod", Algorithm=SHA256)
    etree.SubElement(ref, f"{{{DS}}}DigestValue").text = digest
    value = base64.b64encode(cert.sign(_c14n(signed_info))).decode()
    etree.SubElement(sig, f"{{{DS}}}SignatureValue").text = value
    x509 = etree.SubElement(etree.SubElement(sig, f"{{{DS}}}KeyInfo"), f"{{{DS}}}X509Data")
    etree.SubElement(x509, f"{{{DS}}}X509Certificate").text = cert.der_b64()


def signed_bytes(payload: dict, fic: str, cert: Certificate, *, iban: str = "", due_days: int = 15) -> bytes:
    root = build(payload, fic, iban=iban, due_days=due_days)
    sign(root, cert)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def verify(xml: bytes, public_key) -> bool:
    """Check the invoice signature (used by the tests)."""
    import copy

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    doc = copy.deepcopy(etree.fromstring(xml))
    sig = doc.find(f".//{{{DS}}}Signature")
    signed_info = sig.find(f"{{{DS}}}SignedInfo")
    digest = signed_info.find(f".//{{{DS}}}DigestValue").text
    public_key.verify(
        base64.b64decode(sig.find(f"{{{DS}}}SignatureValue").text), _c14n(signed_info), padding.PKCS1v15(), hashes.SHA256()
    )
    sig.getparent().remove(sig)
    return base64.b64encode(hashlib.sha256(_c14n(doc)).digest()).decode() == digest


def due_date(issue_datetime: str, days: int) -> date:
    return cis.parse_iso(issue_datetime).date() + timedelta(days=days)
