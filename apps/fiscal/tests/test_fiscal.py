import base64
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from django.urls import reverse
from lxml import etree

from apps.core.models import HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase
from apps.fiscal import cis, services, signing
from apps.fiscal.models import CashDeposit, FiscalDocument
from apps.frontdesk import services as fd
from apps.frontdesk.models import Reservation
from apps.outlets import services as pos

D = Decimal
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_p12(password=b"secret") -> bytes:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "L12345678A Test Hotel")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(_KEY.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(_KEY, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"test", _KEY, cert, None, serialization.BestAvailableEncryption(password)
    )


def configure(**extra):
    hs = HotelSettings.load()
    hs.tax_id = "L12345678A"
    hs.legal_name = "Hotel Test sh.p.k."
    hs.address = "Rruga e Kavajës 1"
    hs.currency = "ALL"
    hs.fiscal_enabled = True
    hs.fiscal_business_unit = "ab123ab123"
    hs.fiscal_tcr_code = "cd456cd456"
    hs.fiscal_software_code = "ef789ef789"
    hs.fiscal_operator_code = "op111op111"
    hs.fiscal_certificate = base64.b64encode(make_p12()).decode()
    hs.fiscal_certificate_password = "secret"
    for k, v in extra.items():
        setattr(hs, k, v)
    hs.save()
    return hs


class FakeCIS:
    """Stands in for the tax authority: checks the XML signature and answers with a NIVF."""

    def __init__(self, fail=None):
        self.requests = []
        self.fail = fail

    def __call__(self, xml, action, *, test, timeout=6):
        doc = etree.fromstring(xml)
        body = doc.find(f"{{{cis.SOAP}}}Body")[0]
        assert signing.verify_xml(body, _KEY.public_key()), "bad XML signature"
        self.requests.append((action, body))
        if self.fail == "offline":
            raise cis.CISUnavailable("timed out")
        if self.fail == "reject":
            raise cis.CISError("Invalid IIC", "11")
        ns = cis.NS
        if action == "RegisterCashDeposit":
            return etree.fromstring(f'<r xmlns="{ns}"><FCDC>fcdc-1</FCDC></r>')
        return etree.fromstring(f'<r xmlns="{ns}"><FIC>11111111-2222-3333-4444-555555555555</FIC></r>')

    def invoices(self):
        return [b for a, b in self.requests if a == "RegisterInvoice"]


class SigningTests(HotelTestCase):
    def test_iic_is_md5_of_the_rsa_signature(self):
        cert = signing.Certificate.from_p12(make_p12(), "secret")
        code, sig = signing.iic(cert, ["L12345678A", "2026-10-07T20:30:00+02:00", "1", "bu", "tcr", "sw", "99.01"])
        raw = bytes.fromhex(sig)
        _KEY.public_key().verify(
            raw, b"L12345678A|2026-10-07T20:30:00+02:00|1|bu|tcr|sw|99.01", padding.PKCS1v15(), hashes.SHA256()
        )
        self.assertEqual(code, hashlib.md5(raw).hexdigest().upper())
        self.assertEqual((len(code), len(sig)), (32, 512))

    def test_wrong_password(self):
        with self.assertRaises(signing.CertificateError):
            signing.Certificate.from_p12(make_p12(), "wrong")

    def test_line_amounts_and_vat_groups(self):
        lines = [
            cis.Line("Tavë kosi", "1", "copë", D("2"), D("1200"), D("20")),
            cis.Line("Room", "a", "natë", D("3"), D("5000"), D("6")),
        ]
        t = cis.totals(lines)
        self.assertEqual(t["total"], D("17400.00"))
        self.assertEqual(lines[0].amounts()["PB"], D("2000.00"))
        self.assertEqual(lines[0].amounts()["VA"], D("400.00"))
        self.assertEqual(t["taxes"][D("6")]["vat"], D("849.06"))
        self.assertEqual(cis.quantity(D("2")), "2.00")
        self.assertEqual(cis.quantity(D("0.125")), "0.125")


class FiscalFlowTests(HotelTestCase):
    def setUp(self):
        configure()
        self.cis = FakeCIS()
        p = mock.patch.object(cis, "send", self.cis)
        p.start()
        self.addCleanup(p.stop)
        services._offline_until = None

    def pay(self, method="cash", qty=2):
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter, quantity=qty)
        with self.captureOnCommitCallbacks(execute=True):
            pos.pay_order(order, method=method, user=self.waiter)
        return order

    def test_paid_bill_is_registered_with_codes_and_cash_deposit_first(self):
        order = self.pay()
        doc = order.fiscal_documents.get()
        self.assertEqual(doc.status, FiscalDocument.Status.REGISTERED)
        self.assertEqual(doc.fic, "11111111-2222-3333-4444-555555555555")
        self.assertEqual(doc.inv_num, f"1/{doc.issue_datetime[:4]}/cd456cd456")
        actions = [a for a, _b in self.cis.requests]
        self.assertEqual(actions, ["RegisterCashDeposit", "RegisterInvoice"])
        inv = self.cis.invoices()[0].find(f"{{{cis.NS}}}Invoice")
        self.assertEqual(inv.get("TypeOfInv"), "CASH")
        self.assertEqual(inv.get("TotPrice"), "22.00")
        self.assertEqual(inv.get("TotPriceWoVAT"), "18.33")
        self.assertEqual(inv.get("TotVATAmt"), "3.67")
        self.assertEqual(inv.get("IIC"), doc.iic)
        self.assertEqual(inv.get("OperatorCode"), "op111op111")
        item = inv.find(f".//{{{cis.NS}}}I")
        self.assertEqual((item.get("Q"), item.get("UPA"), item.get("VR")), ("2.00", "11.00", "20.00"))
        pay = inv.find(f".//{{{cis.NS}}}PayMethod")
        self.assertEqual((pay.get("Type"), pay.get("Amt")), ("BANKNOTE", "22.00"))
        # Second sale the same day: no second cash deposit, next ordinal number.
        second = self.pay("card", 1)
        self.assertEqual(second.fiscal_documents.get().inv_ord_num, 2)
        self.assertEqual(CashDeposit.objects.filter(status="registered").count(), 1)

    def test_room_charges_are_fiscalized_on_the_guest_bill_with_two_vat_rates(self):
        res = self.make_reservation(nights=1, status=Reservation.Status.CHECKED_IN)
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter)
        with self.captureOnCommitCallbacks(execute=True):
            pos.charge_to_room(order, res, user=self.waiter)
        self.assertFalse(order.fiscal_documents.exists())
        fd.add_payment(res.folio, amount=D("91"), method="card", user=self.reception)
        with self.captureOnCommitCallbacks(execute=True):
            fd.check_out(res, self.reception)
        doc = res.folio.fiscal_documents.get()
        self.assertEqual(doc.status, FiscalDocument.Status.REGISTERED)
        inv = self.cis.invoices()[-1].find(f"{{{cis.NS}}}Invoice")
        rates = sorted(t.get("VATRate") for t in inv.iter(f"{{{cis.NS}}}SameTax"))
        self.assertEqual(rates, ["20.00", "6.00"])
        self.assertEqual(inv.get("TotPrice"), "91.00")

    def test_offline_sale_gets_nslf_and_is_resent_as_subsequent_delivery(self):
        self.cis.fail = "offline"
        order = self.pay()
        doc = order.fiscal_documents.get()
        self.assertEqual((doc.status, doc.was_offline, doc.fic), ("pending", True, ""))
        self.assertTrue(doc.iic)
        # Next sale doesn't wait for another timeout.
        self.cis.requests.clear()
        self.pay()
        self.assertEqual(self.cis.requests, [])
        self.cis.fail = None
        self.assertEqual(services.resend_pending(), 2)
        header = self.cis.invoices()[0].find(f"{{{cis.NS}}}Header")
        self.assertEqual(header.get("SubseqDelivType"), "NOINTERNET")
        doc.refresh_from_db()
        self.assertEqual(doc.status, "registered")
        # Same IIC as printed on the receipt.
        self.assertEqual(self.cis.invoices()[0].find(f"{{{cis.NS}}}Invoice").get("IIC"), doc.iic)

    def test_rejected_document_is_reported(self):
        self.cis.fail = "reject"
        doc = self.pay().fiscal_documents.get()
        self.assertEqual(doc.status, "failed")
        self.assertIn("Invalid IIC", doc.last_error)
        self.client.login(username="boss", password=PASSWORD)
        self.assertContains(self.client.get("/"), reverse("fiscal:documents"))

    def test_voided_receipt_gets_a_correction(self):
        order = self.pay()
        with self.captureOnCommitCallbacks(execute=True):
            pos.void_receipt(order, user=self.manager, reason="wrong table")
        original = order.fiscal_documents.get(kind="receipt")
        corr = original.corrections.get()
        self.assertEqual(corr.total, D("-22.00"))
        inv = self.cis.invoices()[-1].find(f"{{{cis.NS}}}Invoice")
        ref = inv.find(f"{{{cis.NS}}}CorrectiveInv")
        self.assertEqual((ref.get("IICRef"), ref.get("Type")), (original.iic, "CORRECTIVE"))
        self.assertEqual(inv.get("TotPrice"), "-22.00")

    def test_discount_keeps_totals_exact(self):
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter)
        pos.add_item(order, self.wine, user=self.waiter, quantity=3)
        pos.set_discount(order, user=self.manager, percent=D("10"), reason="regular guest")
        order.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            pos.pay_order(order, method="cash", user=self.waiter)
        inv = self.cis.invoices()[-1].find(f"{{{cis.NS}}}Invoice")
        self.assertEqual(inv.get("TotPrice"), f"{order.total:.2f}")

    def test_nothing_when_disabled(self):
        HotelSettings.objects.filter(pk=1).update(fiscal_enabled=False)
        from apps.core.models import clear_settings_cache

        clear_settings_cache()
        self.assertFalse(self.pay().fiscal_documents.exists())

    def test_receipt_shows_codes_and_qr(self):
        order = self.pay()
        doc = order.fiscal_documents.get()
        self.client.login(username="waiter", password=PASSWORD)
        page = self.client.get(reverse("outlets:receipt", args=[order.pk]))
        self.assertContains(page, doc.iic)
        self.assertContains(page, doc.fic)
        self.assertContains(page, "<svg")
        self.assertIn("efiskalizimi-app-test.tatime.gov.al", doc.verify_url)
        self.assertIn(f"iic={doc.iic}", doc.verify_url)

    def test_escpos_receipt_has_codes(self):
        from apps.outlets import printing
        from apps.outlets.models import Printer

        order = self.pay()
        doc = order.fiscal_documents.get()
        data = printing.receipt_document(order, Printer(name="p", paper_width=80))
        self.assertIn(doc.iic.encode(), data)
        self.assertIn(b"\x1d(k", data)  # QR code command

    def test_pages(self):
        self.pay()
        self.client.login(username="boss", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("fiscal:documents")).status_code, 200)
        self.assertEqual(self.client.get(reverse("core:settings") + "?tab=fiscal").status_code, 200)
        r = self.client.post(reverse("fiscal:cash"), {"operation": "WITHDRAW", "amount": "50"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(CashDeposit.objects.filter(operation="WITHDRAW", status="registered").exists())

    def test_secrets_not_exported(self):
        from apps.core import backup

        hotel = backup.read_file(backup.export_settings())["data"]["hotel"]
        self.assertNotIn("fiscal_certificate", hotel)
        self.assertNotIn("fiscal_certificate_password", hotel)


class FiscalAuditFixTests(HotelTestCase):
    """Regressions from the 2.5 audit."""

    def setUp(self):
        configure(fiscal_since=datetime.now(UTC) - timedelta(hours=1))
        self.cis = FakeCIS()
        p = mock.patch.object(cis, "send", self.cis)
        p.start()
        self.addCleanup(p.stop)
        services._offline_until = None

    def order(self, *items):
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        for item, qty in items:
            pos.add_item(order, item, user=self.waiter, quantity=qty)
        return order

    def test_discount_without_single_items_still_sums_exactly_and_stays_cash(self):
        order = self.order((self.wine, 3))  # 13.50
        pos.set_discount(order, user=self.manager, amount=D("1.00"), reason="regular")
        with self.captureOnCommitCallbacks(execute=True):
            pos.pay_order(order, method="cash", user=self.waiter)
        doc = order.fiscal_documents.get()
        self.assertEqual((doc.total, doc.type_of_inv), (D("12.50"), "CASH"))
        inv = self.cis.invoices()[0].find(f".//{{{cis.NS}}}Invoice")
        self.assertEqual(inv.get("TotPrice"), "12.50")

    def test_part_paid_at_the_table_rest_to_the_room(self):
        res = self.make_reservation(start=0)
        res = fd.check_in(res, self.reception)
        order = self.order((self.dish, 2))  # 22.00
        with self.captureOnCommitCallbacks(execute=True):
            pos.pay_order(order, method="cash", user=self.waiter, amount=D("10"))
            pos.charge_to_room(order, res, user=self.waiter)
        doc = order.fiscal_documents.get()
        self.assertEqual(doc.total, D("10.00"))

    def test_sale_without_a_working_certificate_is_caught_up_later(self):
        HotelSettings.objects.update(fiscal_certificate_password="wrong")
        order = self.order((self.dish, 1))
        with self.captureOnCommitCallbacks(execute=True):
            pos.pay_order(order, method="cash", user=self.waiter)
        self.assertFalse(order.fiscal_documents.exists())
        HotelSettings.objects.update(fiscal_certificate_password="secret")
        order.refresh_from_db()
        type(order).objects.filter(pk=order.pk).update(closed_at=order.closed_at - timedelta(minutes=5))
        from apps.core.models import clear_settings_cache

        clear_settings_cache()
        self.assertEqual(len(services.unfiscalized()), 1)
        services.resend_pending()
        self.assertEqual(order.fiscal_documents.get().status, FiscalDocument.Status.REGISTERED)

    def test_opening_cash_from_the_test_system_does_not_count_when_live(self):
        CashDeposit.objects.create(
            business_date=datetime.now().date(), tcr_code="cd456cd456", operation="INITIAL", amount=D("0"),
            change_datetime=cis.now_str(), status="registered", test=True,
        )
        HotelSettings.objects.update(fiscal_test=False)
        from apps.core.models import clear_settings_cache

        clear_settings_cache()
        order = self.order((self.dish, 1))
        with self.captureOnCommitCallbacks(execute=True):
            pos.pay_order(order, method="cash", user=self.waiter)
        self.assertEqual([a for a, _b in self.cis.requests][0], "RegisterCashDeposit")

    def test_one_bad_document_does_not_block_the_queue(self):
        self.cis.fail = "offline"
        orders = []
        for _ in range(2):
            order = pos.open_order(self.restaurant, label="takeaway", user=self.waiter)
            pos.add_item(order, self.wine, user=self.waiter)
            with self.captureOnCommitCallbacks(execute=True):
                pos.pay_order(order, method="cash", user=self.waiter)
            orders.append(order)
        bad = orders[0].fiscal_documents.get()
        self.assertEqual(bad.status, FiscalDocument.Status.PENDING)
        self.cis.fail = None
        services._offline_until = None
        real = cis.invoice_request

        def request(payload, cert, subsequent=""):
            if payload["invoice"]["inv_num"] == bad.inv_num:
                raise ValueError("All strings must be XML compatible")
            return real(payload, cert, subsequent=subsequent)

        with mock.patch.object(cis, "invoice_request", side_effect=request):
            services.resend_pending()
        bad.refresh_from_db()
        self.assertEqual(bad.status, FiscalDocument.Status.FAILED)
        self.assertEqual(orders[1].fiscal_documents.get().status, FiscalDocument.Status.REGISTERED)

    def test_foreign_currency_sends_the_exchange_rate(self):
        HotelSettings.objects.update(currency="EUR", fiscal_exchange_rate=D("100.5000"))
        from apps.core.models import clear_settings_cache

        clear_settings_cache()
        order = self.order((self.dish, 1))
        with self.captureOnCommitCallbacks(execute=True):
            pos.pay_order(order, method="card", user=self.waiter)
        cur = self.cis.invoices()[0].find(f".//{{{cis.NS}}}Currency")
        self.assertEqual((cur.get("Code"), cur.get("ExRate")), ("EUR", "100.5000"))

    def test_restore_over_data_with_a_correction(self):
        from apps.core import backup

        order = self.order((self.dish, 1))
        with self.captureOnCommitCallbacks(execute=True):
            pos.pay_order(order, method="cash", user=self.waiter)
            pos.void_receipt(order, user=self.manager, reason="wrong table")
        self.assertEqual(FiscalDocument.objects.count(), 2)
        backup.restore_full(backup.read_file(backup.export_full()))
        self.assertEqual(FiscalDocument.objects.count(), 2)
