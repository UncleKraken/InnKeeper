from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from apps.core.models import HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import LoyaltyCard
from apps.marketing import services
from apps.marketing.models import Campaign, CampaignRecipient, Contact


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MarketingTests(HotelTestCase):
    def setUp(self):
        hs = HotelSettings.load()
        hs.smtp_host, hs.smtp_username, hs.email_from = "smtp.example.com", "hotel@example.com", "hotel@example.com"
        hs.public_url = "https://hotel.example"
        hs.save()
        p = mock.patch("apps.core.email.connection", return_value=None)
        p.start()
        self.addCleanup(p.stop)
        k = mock.patch("apps.marketing.services.kick")
        k.start()
        self.addCleanup(k.stop)

    def test_sync_gathers_without_consent_and_dedupes(self):
        self.guest.email, self.guest.phone = "ana@example.com", "069 123 4567"
        self.guest.save()
        self.make_reservation(start=-3, nights=2)
        LoyaltyCard.objects.create(number="1", name="Ana K", phone="+355691234567")
        LoyaltyCard.objects.create(number="2", name="Besi", phone="0681112222")
        self.assertEqual(services.sync_all(), 2)  # Ana once (same phone), Besi
        ana = Contact.objects.get(email="ana@example.com")
        self.assertFalse(ana.marketing_ok)
        self.assertEqual(ana.last_seen, self.today - timedelta(days=1))
        self.assertEqual(services.sync_all(), 0)

    def test_signup_page_records_consent(self):
        r = self.client.post(reverse("news:signup") + "?lang=en", {"name": "Lena", "email": "lena@example.com", "agree": "on"})
        self.assertContains(r, "on our list")
        c = Contact.objects.get()
        self.assertTrue(c.can_email)
        self.assertIn("Sign-up page", c.consent_note)
        r = self.client.post(reverse("news:signup"), {"name": "X", "email": "x@example.com"})
        self.assertEqual(Contact.objects.count(), 1)  # no consent, no contact

    def test_campaign_only_to_those_who_agreed_with_unsubscribe(self):
        yes = Contact.objects.create(name="Yes", email="yes@example.com", marketing_ok=True, language="en")
        Contact.objects.create(name="No", email="no@example.com")
        Contact.objects.create(name="Gone", email="gone@example.com", marketing_ok=True, unsubscribed_at=yes.created_at)
        c = Campaign.objects.create(subject="Summer offer", body="20% off in June: https://hotel.example/book/")
        self.assertEqual(services.start(c, self.manager), 1)
        self.assertEqual(services.run_pending(pause=0), 1)
        msg = mail.outbox[-1]
        self.assertEqual(msg.to, ["yes@example.com"])
        self.assertIn(f"https://hotel.example/news/unsubscribe/{yes.token}/", msg.extra_headers["List-Unsubscribe"])
        c.refresh_from_db()
        self.assertEqual(c.status, "sent")
        # Unsubscribe from the link.
        self.client.post(reverse("news:unsubscribe", args=[yes.token]))
        yes.refresh_from_db()
        self.assertFalse(yes.can_email)
        with self.assertRaises(Exception):
            services.start(c, self.manager)  # not twice

    def test_needs_public_address_and_audience_filters(self):
        Contact.objects.create(name="A", email="a@example.com", marketing_ok=True, language="sq", tags="vip, wedding", last_seen=self.today)
        Contact.objects.create(name="B", email="b@example.com", marketing_ok=True, language="en")
        self.assertEqual(services.audience(Campaign(audience="en")).count(), 1)
        self.assertEqual(services.audience(Campaign(audience="tag", tag="wedding")).count(), 1)
        self.assertEqual(services.audience(Campaign(audience="recent")).count(), 1)
        hs = HotelSettings.load()
        hs.public_url = ""
        hs.save()
        with self.assertRaises(Exception):
            services.start(Campaign.objects.create(subject="x", body="y"), self.manager)

    def test_manual_consent_needs_a_note_and_pages(self):
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.post(reverse("marketing:contact_create"), {"name": "Dita", "email": "dita@example.com", "language": "sq", "marketing_ok": "on"})
        self.assertEqual(r.status_code, 200)
        self.client.post(reverse("marketing:contact_create"), {"name": "Dita", "email": "dita@example.com", "language": "sq", "marketing_ok": "on", "consent_note": "Signed form 12.05"})
        self.assertTrue(Contact.objects.get().consent_at)
        self.assertContains(self.client.get(reverse("marketing:contacts")), "Dita")
        self.assertEqual(self.client.get(reverse("marketing:contacts") + "?format=xlsx").status_code, 200)
        r = self.client.get(reverse("marketing:contacts") + "?format=csv")
        self.assertIn("dita@example.com", r.content.decode("utf-8-sig"))
        self.assertContains(self.client.get(reverse("marketing:signup_poster")), "<svg")
        c = self.client.post(reverse("marketing:campaign_create"), {"subject": "Hi", "body": "News", "audience": "all"})
        camp = Campaign.objects.get()
        self.assertRedirects(c, reverse("marketing:campaign_detail", args=[camp.pk]), fetch_redirect_response=False)
        self.client.post(reverse("marketing:campaign_send", args=[camp.pk]))
        self.assertEqual(CampaignRecipient.objects.count(), 1)

    def test_only_managers(self):
        self.client.login(username="desk", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("marketing:contacts")).status_code, 403)

    def test_online_booking_checkbox(self):
        from apps.frontdesk.public import GuestForm

        self.assertIn("offers", GuestForm().fields)
        self.assertFalse(GuestForm().fields["offers"].required)
