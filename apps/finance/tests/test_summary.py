from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance import summary
from apps.outlets import services as pos


def _at(day, hour):
    return timezone.make_aware(datetime.combine(day, time(hour=hour)))


class DailySummaryTests(HotelTestCase):
    def setUp(self):
        hs = HotelSettings.load()
        hs.smtp_host = "smtp.example.test"
        hs.email_from = "till@example.test"
        hs.summary_to = "owner@example.test, partner@example.test"
        hs.summary_hour = 8
        hs.save()
        clear_settings_cache()

    def _sale(self):
        order = pos.open_order(self.restaurant, user=self.waiter, table=self.table)
        pos.add_item(order, self.dish, user=self.waiter, quantity=2)
        pos.pay_order(order, method="cash", user=self.waiter)
        return order

    def test_summary_content(self):
        self._sale()
        self.assertTrue(summary.send(self.today, force=True))
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["owner@example.test", "partner@example.test"])
        html = m.alternatives[0][0]
        self.assertIn("22", m.subject)
        self.assertIn("Tavë kosi", html)
        self.assertEqual(HotelSettings.objects.get().summary_sent_for, self.today)

    def test_sent_once_at_the_chosen_hour_for_the_day_before(self):
        self._sale()
        tomorrow = self.today + timedelta(days=1)
        self.assertFalse(summary.run(_at(tomorrow, 7)))  # too early
        self.assertEqual(len(mail.outbox), 0)
        clear_settings_cache()
        self.assertTrue(summary.run(_at(tomorrow, 8)))
        clear_settings_cache()
        self.assertFalse(summary.run(_at(tomorrow, 9)))  # only once
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.today.strftime("%d.%m.%Y"), mail.outbox[0].subject)

    def test_quiet_day_sends_nothing(self):
        tomorrow = self.today + timedelta(days=1)
        self.assertFalse(summary.run(_at(tomorrow, 9)))
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(HotelSettings.objects.get().summary_sent_for, self.today)  # not retried every 15 minutes

    def test_nothing_without_email_settings(self):
        HotelSettings.objects.update(smtp_host="")
        clear_settings_cache()
        self._sale()
        self.assertFalse(summary.run(_at(self.today + timedelta(days=1), 9)))
        self.assertEqual(len(mail.outbox), 0)

    def test_night_bar_gets_saturday_night_on_sunday(self):
        HotelSettings.objects.update(day_ends_at=5)
        clear_settings_cache()
        sunday_2am = _at(self.today + timedelta(days=1), 2)
        with mock.patch("django.utils.timezone.now", return_value=sunday_2am):
            self._sale()  # sold at 02:00, belongs to the evening before
        clear_settings_cache()
        self.assertFalse(summary.run(_at(self.today + timedelta(days=1), 6)))  # night over, but before 08:00
        clear_settings_cache()
        self.assertTrue(summary.run(_at(self.today + timedelta(days=1), 8)))
        self.assertIn(self.today.strftime("%d.%m.%Y"), mail.outbox[0].subject)

    def test_day_close_sends_it_straight_away(self):
        self._sale()
        self.client.login(username="boss", password=PASSWORD)
        r = self.client.post(
            reverse("finance:day_close") + f"?date={self.today.isoformat()}",
            {"opening_float": "0", "counted_cash": "20", "notes": ""},
            follow=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("-2", mail.outbox[0].alternatives[0][0].replace("−", "-"))  # counted 20 of 22

    def test_settings_validate_and_send_now(self):
        self.client.login(username="boss", password=PASSWORD)
        self.client.post(reverse("core:summary_settings"), {"summary_to": "nope", "summary_hour": "8"})
        self.assertEqual(HotelSettings.objects.get().summary_to, "owner@example.test, partner@example.test")
        self.client.post(reverse("core:summary_settings"), {"summary_to": "a@b.al; c@d.al", "summary_hour": "7"})
        hs = HotelSettings.objects.get()
        self.assertEqual((hs.summary_to, hs.summary_hour), ("a@b.al, c@d.al", 7))
        self.assertEqual(self.client.get(reverse("core:settings") + "?tab=email").status_code, 200)
        self.client.post(reverse("core:summary_send_now"))
        self.assertEqual(mail.outbox[-1].to, ["a@b.al", "c@d.al"])

    def test_command(self):
        self._sale()
        call_command("daily_summary", "--date", self.today.isoformat(), stdout=mock.MagicMock())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(Decimal("22.00"), summary.build(self.today)["s"]["revenue"])
