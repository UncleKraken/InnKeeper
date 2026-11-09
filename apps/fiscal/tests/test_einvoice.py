from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.urls import reverse
from django.utils import timezone
from lxml import etree

from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Folio
from apps.fiscal import cis, services, ubl
from apps.fiscal.models import FiscalDocument
from apps.frontdesk import services as fd
from apps.frontdesk.models import Reservation

from .test_fiscal import _KEY, FakeCIS, configure

D = Decimal
C = {"cbc": ubl.CBC, "cac": ubl.CAC}


class EinvoiceTests(HotelTestCase):
    def setUp(self):
        configure(bank_iban="AL47212110090000000235698741", einvoice_due_days=30)
        clear_settings_cache()
        self.cis = FakeCIS()
        p = mock.patch.object(cis, "send", self.cis)
        p.start()
        self.addCleanup(p.stop)
        services._offline_until = None

    def _company_stay(self, method="bank_transfer", nuis="M01234567C"):
        res = self.make_reservation(nights=2, status=Reservation.Status.CHECKED_IN)
        folio, _ = Folio.objects.get_or_create(reservation=res)
        if nuis:
            folio.buyer_name, folio.buyer_nuis, folio.buyer_town = "Beta Travel sh.p.k.", nuis, "Durrës"
            folio.save()
        fd.post_accommodation(res, self.reception)
        folio.refresh_from_db()
        if folio.balance > 0 and method:
            fd.add_payment(folio, amount=folio.balance, method=method, user=self.reception)
        with self.captureOnCommitCallbacks(execute=True):
            fd.check_out(res, self.reception)
        return res, FiscalDocument.objects.get(folio=folio)

    def _fiscal_invoice(self):
        return self.cis.invoices()[-1].find(f"{{{cis.NS}}}Invoice")

    def test_company_paying_by_bank_transfer_gets_an_e_invoice(self):
        res, doc = self._company_stay()
        inv = self._fiscal_invoice()
        self.assertEqual((inv.get("TypeOfInv"), inv.get("IsEinvoice")), ("NONCASH", "true"))
        self.assertEqual((doc.einvoice_status, doc.eic), ("registered", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"))
        u = self.cis.einvoices[-1]
        self.assertEqual(u.findtext("cbc:ID", namespaces=C), doc.inv_num)
        self.assertEqual(u.findtext("cbc:CustomizationID", namespaces=C), "urn:cen.eu:en16931:2017")
        self.assertEqual(u.findtext("cbc:InvoiceTypeCode", namespaces=C), "380")
        notes = [n.text for n in u.findall("cbc:Note", namespaces=C)]
        self.assertIn(f"IIC={doc.iic}#AAI#", notes)
        self.assertIn(f"FIC={doc.fic}#AAI#", notes)
        self.assertIn(f"IssueDateTime={doc.issue_datetime}#AAI#", notes)
        self.assertIn("IsBadDebtInv=false#AAI#", notes)
        self.assertEqual(
            u.findtext("cbc:DueDate", namespaces=C), (cis.parse_iso(doc.issue_datetime).date() + timedelta(days=30)).isoformat()
        )
        buyer = u.find("cac:AccountingCustomerParty/cac:Party", namespaces=C)
        self.assertEqual(buyer.findtext("cbc:EndpointID", namespaces=C), "M01234567C")
        self.assertEqual(buyer.find("cbc:EndpointID", namespaces=C).get("schemeID"), "9923")
        self.assertEqual(buyer.findtext("cac:PartyLegalEntity/cbc:RegistrationName", namespaces=C), "Beta Travel sh.p.k.")
        seller = u.find("cac:AccountingSupplierParty/cac:Party", namespaces=C)
        self.assertEqual(seller.findtext("cac:PartyLegalEntity/cbc:CompanyID", namespaces=C), "L12345678A")
        # Paid to the bank account, linked by the NIVF.
        means = u.find("cac:PaymentMeans", namespaces=C)
        self.assertEqual(means.findtext("cbc:PaymentMeansCode", namespaces=C), "30")
        self.assertEqual(means.findtext("cbc:PaymentID", namespaces=C), doc.fic)
        self.assertEqual(means.findtext("cac:PayeeFinancialAccount/cbc:ID", namespaces=C), "AL47212110090000000235698741")
        # Same amounts as the fiscal invoice.
        self.assertEqual(u.findtext("cac:LegalMonetaryTotal/cbc:PayableAmount", namespaces=C), inv.get("TotPrice"))
        self.assertEqual(u.findtext("cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount", namespaces=C), inv.get("TotPriceWoVAT"))
        self.assertEqual(u.findtext("cac:TaxTotal/cbc:TaxAmount", namespaces=C), inv.get("TotVATAmt"))
        lines = u.findall("cac:InvoiceLine", namespaces=C)
        self.assertEqual(len(lines), len(inv.find(f"{{{cis.NS}}}Items")))
        self.assertEqual(
            sum(D(x.findtext("cbc:LineExtensionAmount", namespaces=C)) for x in lines), D(inv.get("TotPriceWoVAT"))
        )
        cats = {c.findtext("cbc:ID", namespaces=C) for c in u.iterfind(".//cac:ClassifiedTaxCategory", namespaces=C)}
        self.assertEqual(cats, {"S"})
        # Shown on the printed invoice and in the documents list.
        self.client.login(username="boss", password=PASSWORD)
        self.assertContains(self.client.get(reverse("frontdesk:invoice", args=[res.pk])), doc.eic)
        self.assertContains(self.client.get(reverse("fiscal:documents")), doc.eic)

    def test_no_e_invoice_for_a_company_paying_by_card_or_a_private_guest(self):
        _res, doc = self._company_stay(method="card")
        self.assertIsNone(self._fiscal_invoice().get("IsEinvoice"))
        self.assertEqual((doc.einvoice_status, self.cis.einvoices), ("", []))
        _res, doc = self._company_stay(nuis="")
        self.assertIsNone(self._fiscal_invoice().get("IsEinvoice"))
        self.assertEqual(doc.einvoice_status, "")

    def test_bills_not_in_lek_keep_the_portal_reminder(self):
        configure(currency="EUR", fiscal_exchange_rate=D("100.50"))
        clear_settings_cache()
        res = self.make_reservation(nights=1, status=Reservation.Status.CHECKED_IN)
        folio, _ = Folio.objects.get_or_create(reservation=res)
        folio.buyer_name, folio.buyer_nuis = "Beta", "M01234567C"
        folio.save()
        fd.add_payment(folio, amount=D("10"), method="bank_transfer", user=self.reception)
        self.client.login(username="desk", password=PASSWORD)
        r = self.client.get(reverse("frontdesk:reservation_detail", args=[res.pk]))
        self.assertContains(r, "alert alert-warning")  # issue it in the self-care portal
        self.assertNotContains(r, "alert alert-info\">")

    def test_open_bill_says_the_e_invoice_will_be_sent(self):
        res = self.make_reservation(nights=1, status=Reservation.Status.CHECKED_IN)
        folio, _ = Folio.objects.get_or_create(reservation=res)
        folio.buyer_name, folio.buyer_nuis = "Beta", "M01234567C"
        folio.save()
        fd.add_payment(folio, amount=D("10"), method="bank_transfer", user=self.reception)
        self.client.login(username="desk", password=PASSWORD)
        r = self.client.get(reverse("frontdesk:reservation_detail", args=[res.pk]))
        self.assertContains(r, "alert alert-info")
        self.assertNotContains(r, "alert alert-warning\">")

    def test_no_connection_then_sent_automatically(self):
        self.cis.fail_einvoice = "offline"
        _res, doc = self._company_stay()
        self.assertEqual((doc.status, doc.einvoice_status, doc.eic), ("registered", "pending", ""))
        self.assertTrue(doc.einvoice_error)
        self.cis.fail_einvoice = None
        FiscalDocument.objects.filter(pk=doc.pk).update(registered_at=timezone.now() - timedelta(minutes=5))
        services.resend_pending()
        doc.refresh_from_db()
        self.assertEqual((doc.einvoice_status, doc.einvoice_error), ("registered", ""))
        self.assertTrue(doc.eic)

    def test_rejected_then_sent_again_from_the_documents_page(self):
        self.cis.fail_einvoice = "reject"
        _res, doc = self._company_stay()
        self.assertEqual(doc.einvoice_status, "failed")
        self.assertIn("12", doc.einvoice_error)
        services.resend_pending()  # a rejection isn't retried on its own
        doc.refresh_from_db()
        self.assertEqual(doc.einvoice_status, "failed")
        self.cis.fail_einvoice = None
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("fiscal:resend", args=[doc.pk]))
        doc.refresh_from_db()
        self.assertEqual(doc.einvoice_status, "registered")
        self.assertEqual(sum(1 for a, _b in self.cis.requests if a == "RegisterInvoice"), 1)  # NIVF not asked twice


class UblTests(HotelTestCase):
    def _payload(self, in_vat=True):
        rate = "20.00" if in_vat else None
        return {
            "nuis": "L12345678A",
            "in_vat": in_vat,
            "currency": "ALL",
            "seller": {"nuis": "L12345678A", "name": "Hotel Test sh.p.k.", "address": "Rr. 1", "town": "Tiranë"},
            "buyer": {"IDType": "NUIS", "IDNum": "M01234567C", "Name": "Beta", "Address": "-", "Town": "-", "Country": "ALB"},
            "lines": [
                {"name": "Dhoma", "code": "accommodation", "unit": "natë", "quantity": "2", "unit_price": "5000", "vat_rate": rate},
                {"name": "Kafe", "code": "", "unit": "copë", "quantity": "3", "unit_price": "120", "vat_rate": rate},
            ],
            "payments": [{"type": "ACCOUNT", "amount": "10360.00"}],
            "invoice": {
                "type": "NONCASH", "issue_datetime": "2026-11-09T10:00:00+01:00", "inv_num": "7/2026/cd456cd456",
                "inv_ord_num": 7, "tcr": "cd456cd456", "operator": "op111op111", "business_unit": "ab123ab123",
                "software": "ef789ef789", "iic": "A" * 32, "iic_signature": "B" * 512, "corrects": None,
                "is_einvoice": True,
            },
        }

    def test_signature_covers_the_whole_invoice(self):
        from apps.fiscal.signing import Certificate

        from .test_fiscal import make_p12

        cert = Certificate.from_p12(make_p12(), "secret")
        xml = ubl.signed_bytes(self._payload(), "11111111-2222-3333-4444-555555555555", cert)
        self.assertTrue(ubl.verify(xml, _KEY.public_key()))
        self.assertFalse(ubl.verify(xml.replace(b">Kafe<", b">Caj<"), _KEY.public_key()))

    def test_vat_and_non_vat_categories_and_night_units(self):
        u = ubl.build(self._payload(), "fic")
        self.assertEqual(u.findtext("cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent", namespaces=C), "20.00")
        q = u.findall("cac:InvoiceLine/cbc:InvoicedQuantity", namespaces=C)
        self.assertEqual([x.get("unitCode") for x in q], ["DAY", "H87"])
        self.assertEqual(u.findtext("cac:PaymentMeans/cbc:PaymentMeansCode", namespaces=C), "42")  # no IBAN set
        u = ubl.build(self._payload(in_vat=False), "fic")
        self.assertEqual(u.findtext("cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID", namespaces=C), "O")
        self.assertEqual(
            u.findtext("cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:TaxExemptionReasonCode", namespaces=C), "vatex-eu-o"
        )
        self.assertEqual(u.findtext("cac:LegalMonetaryTotal/cbc:PayableAmount", namespaces=C), "10360.00")
        self.assertIsNone(u.find("cac:InvoiceLine/cac:Item/cac:ClassifiedTaxCategory/cbc:Percent", namespaces=C))

    def test_register_request_carries_the_invoice_in_base64(self):
        import base64

        from apps.fiscal.signing import Certificate

        from .test_fiscal import make_p12

        cert = Certificate.from_p12(make_p12(), "secret")
        req = etree.fromstring(cis.einvoice_request(b"<Invoice/>", cert))
        body = req.find(f"{{{cis.SOAP}}}Body")[0]
        self.assertEqual((body.tag, body.get("Id"), body.get("Version")), (f"{{{cis.EINVOICE_NS}}}RegisterEinvoiceRequest", "Request", "1"))
        self.assertEqual(base64.b64decode(body.findtext(f".//{{{cis.EINVOICE_NS}}}UblInvoice")), b"<Invoice/>")


class IbanSettingTests(HotelTestCase):
    def test_iban_is_checked(self):
        from apps.core.settings_views import FiscalSettingsForm

        hs = HotelSettings.load()
        for value, ok in (("AL47 2121 1009 0000 0002 3569 8741", True), ("AL47212110090000000235698742", False), ("", True)):
            f = FiscalSettingsForm(data={"bank_iban": value, "einvoice_due_days": 15}, instance=hs)
            f.is_valid()
            self.assertEqual("bank_iban" not in f.errors, ok, value)
            if ok and value:
                self.assertEqual(f.cleaned_data["bank_iban"], "AL47212110090000000235698741")
