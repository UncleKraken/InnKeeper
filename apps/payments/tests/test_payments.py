from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.urls import reverse

from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Payment
from apps.payments import providers, services
from apps.payments.models import PaymentLink

D = Decimal


def set_hs(**values):
    hs = HotelSettings.load()
    for k, v in values.items():
        setattr(hs, k, v)
    hs.save()


class PayseraTests(HotelTestCase):
    def setUp(self):
        hs = HotelSettings.load()
        hs.payment_provider = "paysera"
        hs.paysera_project_id = "12345"
        hs.paysera_password = "secret-pass"
        hs.public_url = "https://hotel.example"
        hs.save()
        self.res = self.make_reservation(start=5)
        self.p = providers.Paysera("12345", "secret-pass", test=True)

    def callback(self, link, **over):
        params = {
            "projectid": "12345",
            "orderid": link.token,
            "amount": str(link.minor_units),
            "currency": link.currency,
            "status": "1",
            "requestid": "987",
            "test": "1",
            **over,
        }
        data = self.p.encode(params)
        return self.client.get(reverse("payments:paysera_callback"), {"data": data, "ss1": self.p.sign(data)})

    def test_checkout_url_is_signed(self):
        link = services.create_link(reservation=self.res, amount=D("48.50"), purpose="deposit")
        url = services.start_checkout(link)
        self.assertTrue(url.startswith("https://bank.paysera.com/pay/?data="))
        from urllib.parse import parse_qs, urlparse

        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.assertEqual(self.p.sign(q["data"]), q["sign"])
        params = self.p.decode(q["data"])
        self.assertEqual((params["amount"], params["currency"], params["orderid"]), ("4850", "EUR", link.token))
        self.assertEqual(params["callbackurl"], "https://hotel.example/pay/paysera/callback/")
        self.assertEqual(params["test"], "1")

    def test_callback_records_payment_on_the_bill(self):
        link = services.create_link(reservation=self.res, amount=D("48.50"), purpose="deposit")
        resp = self.callback(link)
        self.assertEqual(resp.content, b"OK")
        link.refresh_from_db()
        self.assertEqual(link.status, PaymentLink.Status.PAID)
        self.assertEqual(self.res.folio.balance, D("-48.50"))
        self.assertEqual(link.payment.method, Payment.Method.ONLINE)
        # Paysera repeats callbacks: no double payment.
        self.callback(link)
        self.assertEqual(Payment.objects.count(), 1)

    def test_bad_signature_wrong_amount_and_unpaid_status_are_rejected(self):
        link = services.create_link(reservation=self.res, amount=D("20"), purpose="balance")
        data = self.p.encode({"projectid": "12345", "orderid": link.token, "status": "1", "amount": "2000"})
        r = self.client.get(reverse("payments:paysera_callback"), {"data": data, "ss1": "0" * 32})
        self.assertEqual(r.status_code, 400)
        self.callback(link, amount="100")
        link.refresh_from_db()
        self.assertEqual(link.status, PaymentLink.Status.PENDING)
        self.assertIn("100", link.error)
        self.callback(link, status="0")
        link.refresh_from_db()
        self.assertEqual(link.status, PaymentLink.Status.PENDING)

    def test_test_payment_cannot_pay_a_live_link(self):
        set_hs(payment_test_mode=False)
        link = services.create_link(reservation=self.res, amount=D("20"), purpose="balance")
        self.assertEqual(self.callback(link, test="1").status_code, 400)

    def test_guest_deposit_flow_from_booking_page(self):
        set_hs(booking_enabled=True)
        self.res.booking_token = "tok-" + "x" * 20
        self.res.deposit_due = D("30")
        self.res.save()
        status_url = reverse("booking:status", args=[self.res.booking_token])
        self.assertContains(self.client.get(status_url), reverse("booking:pay_deposit", args=[self.res.booking_token]))
        r = self.client.post(reverse("booking:pay_deposit", args=[self.res.booking_token]))
        self.assertTrue(r["Location"].startswith("https://bank.paysera.com/pay/"))
        link = self.res.payment_links.get()
        self.assertEqual((link.purpose, link.amount), ("deposit", D("30.00")))
        # Pressing again reuses the same open link.
        self.client.post(reverse("booking:pay_deposit", args=[self.res.booking_token]))
        self.assertEqual(self.res.payment_links.count(), 1)
        self.callback(link)
        self.assertContains(self.client.get(status_url + "?lang=en"), "Deposit paid by card")

    def test_reception_creates_and_manager_marks_paid(self):
        self.client.login(username="desk", password=PASSWORD)
        self.client.post(
            reverse("payments:create_for_reservation", args=[self.res.pk]),
            {"amount": "75,00", "purpose": "balance", "email": "ana@example.com", "send": "0"},
        )
        link = PaymentLink.objects.get()
        self.assertEqual((link.amount, link.email), (D("75.00"), "ana@example.com"))
        page = self.client.get(reverse("frontdesk:reservation_detail", args=[self.res.pk]))
        self.assertContains(page, f"/pay/{link.token}/")
        self.client.post(reverse("payments:link_action", args=[link.pk]), {"action": "paid"})
        link.refresh_from_db()
        self.assertEqual(link.status, "pending")  # reception may not
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("payments:link_action", args=[link.pk]), {"action": "paid"})
        link.refresh_from_db()
        self.assertEqual(link.status, "paid")

    def test_public_pay_page(self):
        link = services.create_link(reservation=self.res, amount=D("10"), purpose="balance")
        self.assertContains(self.client.get(reverse("payments:pay", args=[link.token])), "10.00")
        r = self.client.post(reverse("payments:pay", args=[link.token]))
        self.assertEqual(r.status_code, 302)
        services.cancel_link(link, self.manager)
        self.assertNotContains(self.client.get(reverse("payments:pay", args=[link.token])), '<form method="post">')

    def test_nothing_without_a_provider(self):
        set_hs(payment_provider="")
        with self.assertRaises(BusinessError):
            services.create_link(reservation=self.res, amount=D("10"), purpose="balance")


class PokTests(HotelTestCase):
    def setUp(self):
        hs = HotelSettings.load()
        hs.payment_provider = "pok"
        hs.pok_key_id, hs.pok_key_secret, hs.pok_merchant_id = "kid", "ksecret", "m-1"
        hs.public_url = "https://hotel.example"
        hs.save()
        self.res = self.make_reservation(start=3)
        self.calls = []

    def fake_http(self, order_state):
        def http(method, url, body=None, headers=None, timeout=20):
            self.calls.append((method, url, body, headers))
            if url.endswith("/auth/sdk/login"):
                return {"data": {"accessToken": "tkn"}}
            if url.endswith("/sdk-orders") and method == "POST":
                return {"data": {"sdkOrder": {"id": "ord-1", "_self": {"confirmUrl": "https://pay.pokpay.io/x"}}}}
            return {"data": {"sdkOrder": {"id": "ord-1", "amount": 25.0, "currencyCode": "EUR", **order_state}}}

        return http

    def test_create_and_webhook_reads_the_order_back(self):
        link = services.create_link(reservation=self.res, amount=D("25"), purpose="deposit")
        with mock.patch.object(providers, "_http", self.fake_http({})):
            url = services.start_checkout(link)
        self.assertEqual(url, "https://pay.pokpay.io/x")
        method, create_url, body, headers = self.calls[1]
        self.assertEqual(create_url, "https://api-staging.pokpay.io/merchants/m-1/sdk-orders")
        self.assertEqual(
            (body["amount"], body["currencyCode"], body["merchantCustomReference"]), ("25.00", "EUR", link.token)
        )
        self.assertEqual(body["webhookUrl"], f"https://hotel.example/pay/pok/{link.token}/")
        self.assertEqual(headers, {"Authorization": "tkn"})
        # A webhook alone doesn't pay: the order must say it's completed.
        with mock.patch.object(providers, "_http", self.fake_http({})):
            self.client.post(reverse("payments:pok_webhook", args=[link.token]), {"anything": "1"})
        link.refresh_from_db()
        self.assertEqual(link.status, "pending")
        self.assertTrue(link.error)
        with mock.patch.object(providers, "_http", self.fake_http({"isCompleted": True})):
            self.assertEqual(self.client.post(reverse("payments:pok_webhook", args=[link.token])).content, b"OK")
        link.refresh_from_db()
        self.assertEqual(link.status, "paid")
        self.assertEqual(self.res.folio.balance, D("-25.00"))

    def test_return_page_checks_status(self):
        link = services.create_link(reservation=self.res, amount=D("25"), purpose="deposit")
        link.external_id = "ord-1"
        link.save()
        with mock.patch.object(providers, "_http", self.fake_http({"status": "CAPTURED"})):
            r = self.client.get(reverse("payments:done", args=[link.token]) + "?lang=en")
        self.assertContains(r, "Payment received")

    def test_provider_errors_are_shown_kindly(self):
        link = services.create_link(reservation=self.res, amount=D("25"), purpose="deposit")
        with mock.patch.object(providers, "_http", side_effect=providers.ProviderError("HTTP 401")):
            with self.assertRaises(BusinessError):
                services.start_checkout(link)
        link.refresh_from_db()
        self.assertIn("401", link.error)

    def test_pok_rejects_other_currencies(self):
        set_hs(currency="USD")
        link = services.create_link(reservation=self.res, amount=D("25"), purpose="deposit")
        with mock.patch.object(providers, "_http", self.fake_http({})), self.assertRaises(BusinessError):
            services.start_checkout(link)

    def test_settings_tab(self):
        self.client.login(username="boss", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("core:settings") + "?tab=payments").status_code, 200)
        r = self.client.post(reverse("core:settings") + "?tab=payments", {"payment_provider": "paysera"})
        self.assertEqual(r.status_code, 200)  # missing project id / password
        self.assertContains(r, "error")


class ExpiredLinkTests(HotelTestCase):
    def test_paid_links_survive_full_backup(self):
        from apps.core import backup

        hs = HotelSettings.load()
        hs.payment_provider, hs.paysera_project_id, hs.paysera_password = "paysera", "1", "p"
        hs.save()
        res = self.make_reservation(start=1, nights=1)
        services.create_link(reservation=res, amount=D("5"), purpose="deposit")
        backup.restore_full(backup.read_file(backup.export_full()))
        self.assertEqual(PaymentLink.objects.count(), 1)
        self.assertEqual(res.departure, self.today + timedelta(days=2))
