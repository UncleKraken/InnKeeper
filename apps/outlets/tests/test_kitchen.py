import socket
import threading
from decimal import Decimal

from django.urls import reverse

from apps.core.testing import PASSWORD, HotelTestCase
from apps.accounts.models import Role, User
from apps.outlets import printing, services
from apps.outlets.models import Category, Item, KitchenTicket, OrderLine, Printer, PrintJob, Station


class FakePrinter:
    """A tiny TCP server that records what an ESC/POS printer would receive."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.received: list[bytes] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _addr = self.sock.accept()
            except OSError:
                return
            chunks = []
            with conn:
                while data := conn.recv(4096):
                    chunks.append(data)
            self.received.append(b"".join(chunks))

    def wait(self, n=1, timeout=3.0):
        import time

        end = time.monotonic() + timeout
        while len(self.received) < n and time.monotonic() < end:
            time.sleep(0.02)
        return self.received

    def close(self):
        self.sock.close()


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class KitchenFlowTests(HotelTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.kitchen = Station.objects.create(name="Kitchen")
        cls.bar = Station.objects.create(name="Bar")
        cls.food = Category.objects.create(outlet=cls.restaurant, name="Food", station=cls.kitchen)
        cls.drinks = Category.objects.create(outlet=cls.restaurant, name="Drinks", station=cls.bar)
        cls.soup = Item.objects.create(category=cls.food, name="Soup", price=Decimal("5.00"))
        cls.beer = Item.objects.create(category=cls.drinks, name="Beer", price=Decimal("3.00"))
        cls.cook = User.objects.create_user("cook", password=PASSWORD, role=Role.KITCHEN)

    def order(self):
        return services.open_order(self.restaurant, table=self.table, user=self.waiter)

    def test_items_without_a_station_are_served_directly(self):
        order = self.order()
        line = services.add_item(order, self.dish, user=self.waiter)  # "Mains" has no station
        self.assertEqual(line.status, OrderLine.Status.DIRECT)
        self.assertEqual(services.send_to_kitchen(order, user=self.waiter), [])

    def test_send_creates_one_ticket_per_station(self):
        order = self.order()
        services.add_item(order, self.soup, user=self.waiter, quantity=2)
        services.add_item(order, self.beer, user=self.waiter)
        self.assertEqual(order.unsent_count, 2)
        tickets = services.send_to_kitchen(order, user=self.waiter)
        self.assertEqual({t.station for t in tickets}, {self.kitchen, self.bar})
        self.assertEqual(order.unsent_count, 0)
        line = order.lines.get(item=self.soup)
        self.assertEqual((line.status, line.sent_quantity), (OrderLine.Status.SENT, 2))
        # Sending again does nothing.
        self.assertEqual(services.send_to_kitchen(order, user=self.waiter), [])

    def test_more_of_a_sent_item_becomes_a_new_line(self):
        order = self.order()
        line = services.add_item(order, self.soup, user=self.waiter)
        services.send_to_kitchen(order, user=self.waiter)
        line.refresh_from_db()
        new = services.change_quantity(line, +1, user=self.waiter)
        self.assertNotEqual(new.pk, line.pk)
        self.assertEqual(new.status, OrderLine.Status.NEW)
        self.assertEqual(order.total, Decimal("10.00"))

    def test_removing_a_sent_item_keeps_it_for_the_kitchen_and_cancels_an_empty_ticket(self):
        order = self.order()
        line = services.add_item(order, self.soup, user=self.waiter)
        (ticket,) = services.send_to_kitchen(order, user=self.waiter)
        line.refresh_from_db()
        self.assertIsNone(services.change_quantity(line, -1, user=self.waiter))
        line.refresh_from_db()
        self.assertEqual((line.quantity, line.sent_quantity), (0, 1))
        self.assertEqual(list(order.active_lines), [])
        self.assertEqual(order.total, Decimal("0"))
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, KitchenTicket.Status.CANCELLED)

    def test_paying_sends_whatever_is_left(self):
        order = self.order()
        services.add_item(order, self.soup, user=self.waiter)
        services.pay_order(order, method="cash", user=self.waiter)
        self.assertEqual(KitchenTicket.objects.filter(order=order).count(), 1)

    def test_cancelling_an_order_cancels_its_tickets(self):
        order = self.order()
        services.add_item(order, self.soup, user=self.waiter)
        (ticket,) = services.send_to_kitchen(order, user=self.waiter)
        services.change_quantity(order.lines.get(), -1, user=self.waiter)
        services.cancel_order(order, user=self.waiter)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, KitchenTicket.Status.CANCELLED)

    def test_ticket_status_timestamps(self):
        order = self.order()
        services.add_item(order, self.soup, user=self.waiter)
        (ticket,) = services.send_to_kitchen(order, user=self.waiter)
        services.set_ticket_status(ticket, KitchenTicket.Status.PREPARING, user=self.cook)
        services.set_ticket_status(ticket, KitchenTicket.Status.READY, user=self.cook)
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.started_at)
        self.assertIsNotNone(ticket.ready_at)

    def test_kitchen_screen_and_status_buttons(self):
        order = self.order()
        services.add_item(order, self.soup, user=self.waiter, note="no salt")
        (ticket,) = services.send_to_kitchen(order, user=self.waiter)
        self.client.login(username="cook", password=PASSWORD)
        self.assertRedirects(self.client.get("/"), reverse("outlets:board_home"), fetch_redirect_response=False)
        r = self.client.get(reverse("outlets:board_tickets", args=[self.kitchen.pk]))
        self.assertContains(r, "Soup")
        self.assertContains(r, "no salt")
        self.assertEqual(r["X-New-Tickets"], str(ticket.pk))
        self.assertNotContains(self.client.get(reverse("outlets:board_tickets", args=[self.bar.pk])), "Soup")
        r = self.client.post(
            reverse("outlets:ticket_status", args=[ticket.pk]), {"status": "ready"}, HTTP_X_REQUESTED_WITH="fetch"
        )
        self.assertEqual(r.json(), {"ok": True})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, KitchenTicket.Status.READY)
        # The cook has no access to the tills.
        self.assertEqual(self.client.get(reverse("finance:dashboard")).status_code, 403)

    def test_floor_signature_changes_when_an_order_changes(self):
        self.client.login(username="waiter", password=PASSWORD)
        url = reverse("outlets:floor_signature", args=[self.restaurant.pk])
        before = self.client.get(url).json()["sig"]
        order = self.order()
        services.add_item(order, self.soup, user=self.waiter)
        self.assertNotEqual(before, self.client.get(url).json()["sig"])


class PrintingTests(HotelTestCase):
    def setUp(self):
        self.fake = FakePrinter()
        self.addCleanup(self.fake.close)
        self.printer = Printer.objects.create(name="Front", address="127.0.0.1", port=self.fake.port)

    def test_receipt_builder_produces_escpos(self):
        data = printing.Receipt(58).text("Hotel", bold=True, align="center").pair("Total", "12.00").cut().to_bytes()
        self.assertTrue(data.startswith(b"\x1b@"))
        self.assertIn(b"Hotel", data)
        self.assertIn(b"\x1dV", data)  # cut

    def test_receipt_document_lists_items_and_total(self):
        order = services.open_order(self.restaurant, table=self.table, user=self.waiter)
        services.add_item(order, self.dish, user=self.waiter, quantity=2)
        self.printer.open_drawer = True
        data = printing.receipt_document(order, self.printer, open_drawer=True)
        self.assertIn("Tavë kosi".encode("cp1252"), data)
        self.assertIn(b"22.00", data)
        self.assertIn(b"\x1bp", data)  # drawer kick

    def test_submit_sends_to_a_network_printer(self):
        job = printing.submit(self.printer, "Test", printing.test_document(self.printer))
        self.assertEqual(job.status, PrintJob.Status.DONE)
        self.assertIn(b"InnKeeper", self.fake.wait()[0])

    def test_failed_job_is_kept_and_can_be_retried(self):
        self.printer.port = free_port()
        self.printer.save()
        job = printing.submit(self.printer, "Test", b"hello")
        self.assertEqual(job.status, PrintJob.Status.FAILED)
        self.assertIn("127.0.0.1", job.error)
        self.printer.port = self.fake.port
        self.printer.save()
        job.refresh_from_db()
        printing.run_job(job)
        self.assertEqual((job.status, job.attempts), (PrintJob.Status.DONE, 2))
        self.assertEqual(self.fake.wait(), [b"hello"])

    def test_switched_off_printer_does_not_print(self):
        self.printer.is_active = False
        self.printer.save()
        self.assertEqual(printing.submit(self.printer, "x", b"x").status, PrintJob.Status.FAILED)

    def test_station_printer_gets_the_ticket_after_commit(self):
        station = Station.objects.create(name="Kitchen", printer=self.printer)
        cat = Category.objects.create(outlet=self.restaurant, name="Food", station=station)
        soup = Item.objects.create(category=cat, name="Soup", price=Decimal("5.00"))
        order = services.open_order(self.restaurant, table=self.table, user=self.waiter)
        services.add_item(order, soup, user=self.waiter, quantity=3)
        with self.captureOnCommitCallbacks(execute=True):
            services.send_to_kitchen(order, user=self.waiter)
        data = self.fake.wait()[0]
        self.assertIn(b"Soup", data)
        self.assertIn(b"KITCHEN", data.upper())
