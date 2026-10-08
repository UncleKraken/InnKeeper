"""Regression tests for the bugs found in the 2.5 audit (money, front desk, restaurant, security)."""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import RequestFactory
from django.urls import reverse

from apps.core.exceptions import BusinessError
from apps.core.middleware import client_ip
from apps.core.models import SafeCSVWriter
from apps.core.testing import PASSWORD, HotelTestCase
from apps.finance.models import Folio, Payment
from apps.finance.reports import day_summary
from apps.frontdesk import ical, services
from apps.frontdesk.forms import ReservationForm
from apps.frontdesk.groups import create_group, group_check_out
from apps.frontdesk.models import CalendarFeed, Reservation
from apps.housekeeping import services as hk
from apps.housekeeping.models import HousekeepingTask, MaintenanceTicket
from apps.outlets import services as pos
from apps.outlets.models import Category, KitchenTicket, Order, Station, Table

D = Decimal


class StayMoneyTests(HotelTestCase):
    def in_house(self, *, room=None, arrived=1, nights=2):
        res = self.make_reservation(room=room, start=0, nights=nights)
        Reservation.objects.filter(pk=res.pk).update(
            arrival=self.today - timedelta(days=arrived), departure=self.today - timedelta(days=arrived) + timedelta(days=nights)
        )
        Reservation.objects.filter(pk=res.pk).update(status=Reservation.Status.CHECKED_IN)
        res.refresh_from_db()
        Folio.objects.get_or_create(reservation=res)
        return res

    def test_a_voided_night_is_not_posted_again(self):
        res = self.in_house(arrived=1, nights=2)
        services.night_audit(self.today)
        (night,) = res.folio.charges.all()
        self.assertEqual(night.business_date, res.arrival)  # dated on the night itself
        services.void_entry(night, reason="waived", user=self.manager)
        services.night_audit(self.today)
        self.assertEqual(res.folio.charges.count(), 1)
        self.assertEqual(res.accommodation_nights_posted(), 1)

    def test_overpaid_bill_needs_a_refund_before_check_out(self):
        res = self.in_house(arrived=1, nights=1)
        services.add_payment(res.folio, amount=D("100"), method="cash", user=self.reception)
        with self.assertRaises(BusinessError):
            services.check_out(res, self.reception)
        services.post_accommodation(res, self.reception)
        services.add_payment(res.folio, amount=D("-20"), method="cash", user=self.reception)  # within the credit
        services.check_out(res, self.reception)
        res.folio.refresh_from_db()
        self.assertEqual((res.folio.status, res.folio.balance), (Folio.Status.CLOSED, D("0")))
        self.assertTrue(res.folio.invoice_number)

    def test_large_refunds_need_a_manager(self):
        res = self.in_house()
        with self.assertRaises(BusinessError):
            services.add_payment(res.folio, amount=D("-500"), method="cash", user=self.reception)
        services.add_payment(res.folio, amount=D("-500"), method="cash", user=self.manager)

    def test_no_show_fee_paid_closes_the_bill(self):
        res = self.make_reservation(start=0)
        folio, _ = Folio.objects.get_or_create(reservation=res)
        services.add_charge(folio, description="No-show fee", quantity=1, unit_price=D("50"), user=self.reception)
        services.add_payment(folio, amount=D("50"), method="card", user=self.reception)
        services.cancel(res, self.reception, no_show=True)
        folio.refresh_from_db()
        self.assertEqual(folio.status, Folio.Status.CLOSED)
        self.assertTrue(folio.invoice_number)

    def test_voiding_yesterday_does_not_change_yesterdays_day_close(self):
        res = self.in_house()
        yesterday = self.today - timedelta(days=1)
        p = services.add_payment(res.folio, amount=D("30"), method="cash", user=self.reception)
        Payment.objects.filter(pk=p.pk).update(business_date=yesterday)
        p.refresh_from_db()
        services.void_entry(p, reason="wrong", user=self.manager)
        self.assertEqual(day_summary(yesterday)["cash"], D("30"))
        self.assertEqual(day_summary(self.today)["cash"], D("-30"))

    def test_online_payments_are_in_the_day_close(self):
        res = self.in_house()
        services.add_payment(res.folio, amount=D("50"), method=Payment.Method.ONLINE, user=None)
        services.add_payment(res.folio, amount=D("10"), method="cash", user=self.reception)
        s = day_summary(self.today)
        self.assertEqual(s["received"], s["cash"] + s["card"] + s["other"])

    def test_late_check_out_never_runs_into_the_next_booking(self):
        a = self.in_house(arrived=2, nights=1)  # should have left yesterday
        b = self.make_reservation(start=-1, nights=3)
        services.check_out(a, self.reception, allow_balance=True)
        a.refresh_from_db()
        self.assertEqual(a.departure, b.arrival)

    def test_same_day_check_out_shortens_the_stay(self):
        res = self.make_reservation(start=0, nights=5)
        res = services.check_in(res, self.reception)
        services.check_out(res, self.reception, allow_balance=True)
        res.refresh_from_db()
        self.assertEqual(res.nights, 1)

    def test_editing_a_note_keeps_the_channel_prices(self):
        res = self.make_reservation(start=3, nights=2)
        Reservation.objects.filter(pk=res.pk).update(nightly_rates=["95.00", "120.00"], rate=D("107.50"))
        res.refresh_from_db()
        data = {f: getattr(res, f) for f in ("arrival", "departure", "adults", "children", "source", "external_ref")}
        data |= {"room": res.room_id, "notes": "late arrival", "rate": ""}
        form = ReservationForm(data=data, instance=res)
        self.assertTrue(form.is_valid(), form.errors)
        services.save_reservation(form.save(commit=False), self.reception)
        res.refresh_from_db()
        self.assertEqual((res.nightly_rates, res.amount_for_nights(0, 2)), (["95.00", "120.00"], D("215.00")))

    def test_in_house_room_change_must_use_move_room(self):
        res = self.make_reservation(start=0)
        services.check_in(res, self.reception)
        res.room = self.room2
        with self.assertRaises(BusinessError):
            services.save_reservation(res, self.reception)

    def test_out_of_order_room_cannot_be_booked_today(self):
        self.room2.out_of_order = True
        self.room2.save()
        with self.assertRaises(BusinessError):
            self.make_reservation(room=self.room2, start=0)

    def test_move_room_with_new_rate_drops_old_night_prices(self):
        res = self.make_reservation(start=3, nights=2)
        Reservation.objects.filter(pk=res.pk).update(nightly_rates=["95.00", "95.00"])
        res.refresh_from_db()
        self.double.base_rate = D("100")
        self.double.save()
        services.move_room(res, self.room2, self.reception, use_new_rate=True)
        res.refresh_from_db()
        self.assertEqual(res.amount_for_nights(0, 2), D("200.00"))

    def test_restaurant_charges_are_voided_through_the_receipt(self):
        res = self.in_house()
        order = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(order, self.dish, user=self.waiter)
        pos.charge_to_room(order, res, user=self.waiter)
        charge = res.folio.charges.get(order=order)
        with self.assertRaises(BusinessError):
            services.void_entry(charge, reason="x", user=self.manager)


class GroupBillTests(HotelTestCase):
    def group(self, nights):
        return create_group(
            name="Tour", contact=self.guest, rooms=[self.room, self.room2], arrival=self.today,
            departure=self.today + timedelta(days=nights), adults=2, user=self.reception,
        )

    def test_main_room_checking_out_first_does_not_charge_others_twice(self):
        group = self.group(nights=2)
        main, other = group.master, group.reservations.exclude(pk=group.master_id).get()
        for r in (main, other):
            services.check_in(r, self.reception)
        Reservation.objects.filter(pk__in=[main.pk, other.pk]).update(arrival=self.today - timedelta(days=1))
        main.refresh_from_db()
        group_check_out(main, self.reception, allow_balance=True)
        other.refresh_from_db()
        self.assertEqual(other.accommodation_nights_posted(), 1)
        services.night_audit(self.today + timedelta(days=1))
        self.assertEqual(other.accommodation_nights_posted(), 2)  # night 2 only, not night 1 again

    def test_cancelled_main_room_does_not_collect_the_group(self):
        group = self.group(nights=1)
        main, other = group.master, group.reservations.exclude(pk=group.master_id).get()
        Folio.objects.get_or_create(reservation=main)
        services.cancel(main, self.reception)
        services.check_in(other, self.reception)
        with self.assertRaises(BusinessError):  # pays its own bill now
            group_check_out(other, self.reception)


class HousekeepingAndCalendarTests(HotelTestCase):
    def test_check_out_with_two_pending_departure_cleans(self):
        for _ in range(2):
            HousekeepingTask.objects.create(room=self.room, kind=HousekeepingTask.Kind.DEPARTURE)
        res = self.make_reservation(start=0, nights=1)
        res = services.check_in(res, self.reception)
        services.check_out(res, self.reception, allow_balance=True)

    def test_moving_a_ticket_frees_the_first_room(self):
        t = hk.save_ticket(MaintenanceTicket(title="Leak", room=self.room, blocks_room=True), self.manager)
        self.room.refresh_from_db()
        self.assertTrue(self.room.out_of_order)
        t.room = self.room2
        hk.save_ticket(t, self.manager)
        self.room.refresh_from_db()
        self.assertFalse(self.room.out_of_order)

    def test_one_empty_calendar_does_not_cancel_bookings(self):
        feed = CalendarFeed.objects.create(room=self.room, source="booking_com", url="https://example.com/a.ics")
        d = self.today + timedelta(days=3)
        full = "\r\n".join(
            ["BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:b1", f"DTSTART;VALUE=DATE:{d:%Y%m%d}",
             f"DTEND;VALUE=DATE:{d + timedelta(days=2):%Y%m%d}", "END:VEVENT", "END:VCALENDAR"]
        )
        empty = "BEGIN:VCALENDAR\r\nEND:VCALENDAR"
        for text in (full, empty):
            with mock.patch.object(ical, "fetch", return_value=text):
                ical.sync_feed(feed)
        self.assertEqual(Reservation.objects.get(external_uid="b1").status, Reservation.Status.BOOKED)
        with mock.patch.object(ical, "fetch", return_value=empty):
            ical.sync_feed(feed)  # empty twice: really gone
        self.assertEqual(Reservation.objects.get(external_uid="b1").status, Reservation.Status.CANCELLED)

    def test_rack_with_a_bad_days_value(self):
        self.client.login(username="desk", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("frontdesk:rack") + "?days=abc").status_code, 200)


class TillTests(HotelTestCase):
    def order(self, *items, table=None):
        o = pos.open_order(self.restaurant, table=table or self.table, user=self.waiter)
        for item, qty in items:
            pos.add_item(o, item, user=self.waiter, quantity=qty)
        return o

    def test_double_tap_on_a_split_payment_is_refused(self):
        o = self.order((self.dish, 2))
        self.client.login(username="waiter", password=PASSWORD)
        post = {"how": "cash", "amount": "11.00", "remaining": "22.00"}
        self.client.post(reverse("outlets:settle", args=[o.pk]), post)
        self.client.post(reverse("outlets:settle", args=[o.pk]), post)
        self.assertEqual(o.payments.filter(voided=False).count(), 1)

    def test_removing_items_keeps_the_discount_within_the_staff_limit(self):
        from apps.core.models import HotelSettings

        HotelSettings.objects.update(max_staff_discount=D("10"))
        o = self.order((self.dish, 1), (self.wine, 2))  # 20.00
        pos.set_discount(o, user=self.waiter, percent=D("10"), reason="regular")
        pos.change_quantity(o.lines.get(item=self.dish), -1, user=self.waiter)
        o.refresh_from_db()
        self.assertLessEqual(o.discount, D("0.90"))  # 10% of the 9.00 left

    def test_a_fully_discounted_bill_can_be_closed(self):
        o = self.order((self.dish, 1))
        pos.set_discount(o, user=self.manager, percent=D("100"), reason="staff meal")
        pos.pay_order(o, method="cash", user=self.manager)
        o.refresh_from_db()
        self.assertEqual((o.status, o.total), (Order.Status.CLOSED, D("0")))

    def test_merging_tables_keeps_the_discount(self):
        a = self.order((self.dish, 2))
        pos.set_discount(a, user=self.manager, amount=D("10"), reason="voucher")
        other = Table.objects.create(outlet=self.restaurant, name="2")
        b = self.order((self.dish, 2), table=other)
        pos.move_order(a, other, user=self.waiter)
        b.refresh_from_db()
        self.assertEqual(b.total, D("34.00"))

    def test_a_cancelled_ticket_cannot_come_back(self):
        Category.objects.filter(outlet=self.restaurant).update(station=Station.objects.create(name="Kitchen"))
        o = self.order((self.dish, 1))
        (ticket,) = pos.send_to_kitchen(o, user=self.waiter)
        pos.change_quantity(o.lines.get(), -1, user=self.waiter)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, KitchenTicket.Status.CANCELLED)
        pos.set_ticket_status(ticket, KitchenTicket.Status.READY, user=self.waiter)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, KitchenTicket.Status.CANCELLED)

    def test_sold_out_items_cannot_be_increased(self):
        o = self.order((self.dish, 1))
        self.dish.is_active = False
        self.dish.save()
        with self.assertRaises(BusinessError):
            pos.change_quantity(o.lines.get(), 1, user=self.waiter)


class SecurityTests(HotelTestCase):
    def test_admin_sign_in_goes_through_the_locked_login(self):
        r = self.client.get("/admin/login/?next=/admin/")
        self.assertRedirects(r, reverse("accounts:login") + "?next=/admin/", fetch_redirect_response=False)

    def test_visitor_address_behind_a_local_tunnel(self):
        rf = RequestFactory()
        self.assertEqual(client_ip(rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_CF_CONNECTING_IP="203.0.113.9")), "203.0.113.9")
        # Only the local tunnel is trusted to say who the visitor is.
        self.assertEqual(client_ip(rf.get("/", REMOTE_ADDR="192.168.1.20", HTTP_CF_CONNECTING_IP="1.2.3.4")), "192.168.1.20")

    def test_csv_cells_cannot_be_formulas(self):
        import io

        out = io.StringIO()
        SafeCSVWriter(out).writerow(['=HYPERLINK("http://x")', "Ana", D("-5")])
        self.assertTrue(out.getvalue().startswith('"\'=HYPERLINK'))
        self.assertIn(",-5", out.getvalue())

    def test_cookies_are_secure_over_https(self):
        r = self.client.post(
            reverse("accounts:login"), {"username": "boss", "password": PASSWORD}, secure=True
        )
        self.assertTrue(r.cookies["sessionid"]["secure"])

    def test_staff_cannot_cancel_after_removing_sent_items(self):
        Category.objects.filter(outlet=self.restaurant).update(station=Station.objects.create(name="Kitchen"))
        o = pos.open_order(self.restaurant, table=self.table, user=self.waiter)
        pos.add_item(o, self.dish, user=self.waiter)
        pos.send_to_kitchen(o, user=self.waiter)
        pos.change_quantity(o.lines.get(), -1, user=self.waiter)
        with self.assertRaises(BusinessError):
            pos.cancel_order(o, user=self.waiter)
