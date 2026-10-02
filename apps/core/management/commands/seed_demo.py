"""
Fill an empty database with a realistic demo hotel so you can try every screen.

    python manage.py seed_demo

Never run this on a live hotel's database.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.models import HotelSettings
from apps.finance.models import Expense
from apps.frontdesk import services as fd
from apps.frontdesk.models import Guest, Reservation, Room, RoomType
from apps.housekeeping.models import HousekeepingTask, MaintenanceTicket
from apps.outlets import services as pos
from apps.outlets.models import Category, Item, Outlet, Table

STAFF = [
    ("manager", "Arta", "Hoxha", Role.MANAGER),
    ("reception", "Elira", "Krasniqi", Role.RECEPTION),
    ("housekeeping", "Mimoza", "Dervishi", Role.HOUSEKEEPING),
    ("maintenance", "Gentian", "Leka", Role.MAINTENANCE),
    ("waiter", "Dritan", "Shehu", Role.OUTLET),
    ("bar", "Klea", "Basha", Role.OUTLET),
    ("spa", "Ina", "Gjoka", Role.OUTLET),
    ("finance", "Besnik", "Malaj", Role.FINANCE),
]

MENUS = {
    ("Restaurant", Outlet.Kind.RESTAURANT, True, 12): {
        "Starters": [("Sallatë fshati", "6.00"), ("Byrek me spinaq", "4.50"), ("Djathë i bardhë me ullinj", "5.00")],
        "Mains": [
            ("Tavë kosi", "11.00"),
            ("Fërgesë Tirane", "9.50"),
            ("Grilled sea bass", "16.00"),
            ("Pasta with seafood", "13.00"),
        ],
        "Desserts": [("Trilece", "4.00"), ("Bakllava", "4.50"), ("Ice cream (2 scoops)", "3.50")],
    },
    ("Lobby Bar", Outlet.Kind.BAR, True, 8): {
        "Coffee": [("Espresso", "1.50"), ("Macchiato", "1.80"), ("Cappuccino", "2.20")],
        "Soft drinks": [("Water 0.5L", "1.00"), ("Coca-Cola 0.33L", "2.50"), ("Fresh orange juice", "3.50")],
        "Wine & spirits": [("House wine (glass)", "4.00"), ("Raki rrushi", "3.00"), ("Skanderbeg cognac", "4.50")],
        "Beer": [("Birra Korça 0.5L", "3.00"), ("Birra Tirana 0.5L", "3.00")],
    },
    ("Spa", Outlet.Kind.SPA, False, 0): {
        "Massages": [
            ("Relax massage 50′", "45.00", 50),
            ("Deep tissue 50′", "55.00", 50),
            ("Couples massage 80′", "120.00", 80),
        ],
        "Wellness": [("Sauna & hammam", "15.00", 90), ("Facial treatment", "40.00", 45)],
    },
    ("Room Service", Outlet.Kind.ROOM_SERVICE, False, 0): {
        "Breakfast": [("Continental breakfast", "12.00"), ("Albanian breakfast", "14.00")],
        "Night menu": [("Club sandwich", "9.00"), ("Pizza Margherita", "10.00")],
    },
    ("Laundry", Outlet.Kind.LAUNDRY, False, 0): {
        "Wash & iron": [("Shirt", "3.00"), ("Trousers", "4.00"), ("Suit", "12.00")],
    },
}

CATEGORY_SQ = {
    "Starters": "Antipasta",
    "Mains": "Pjata kryesore",
    "Desserts": "Ëmbëlsira",
    "Coffee": "Kafe",
    "Soft drinks": "Pije freskuese",
    "Wine & spirits": "Verë & pije alkoolike",
    "Beer": "Birra",
    "Massages": "Masazhe",
    "Wellness": "Mirëqenie",
    "Breakfast": "Mëngjes",
    "Night menu": "Menu nate",
    "Wash & iron": "Larje & hekurosje",
}

GUESTS = [
    ("Ardit", "Gashi", "AL"),
    ("Sara", "Rossi", "IT"),
    ("Lukas", "Müller", "DE"),
    ("Emma", "Dubois", "FR"),
    ("Jonida", "Prifti", "AL"),
    ("Oliver", "Smith", "GB"),
    ("Ana", "García", "ES"),
    ("Erion", "Kola", "XK"),
    ("Mila", "Novak", "SI"),
    ("Noah", "Johnson", "US"),
    ("Blerta", "Hysa", "AL"),
    ("Marco", "Bianchi", "IT"),
]


class Command(BaseCommand):
    help = "Create a demo hotel with rooms, staff, outlets, guests and stays."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="", help="Password for all demo staff accounts.")
        parser.add_argument("--yes", action="store_true", help="Allow running with DEBUG off.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["yes"]:
            raise CommandError("DEBUG is off. This looks like a live system; pass --yes only if you are sure.")
        if Room.objects.exists() or Reservation.objects.exists():
            raise CommandError("The database already has rooms or reservations. Use a fresh database for the demo.")

        password = opts["password"] or "demo-" + "".join(random.choices("abcdefghjkmnpqrstuvwxyz23456789", k=8))
        random.seed(7)
        today = timezone.localdate()

        hotel = HotelSettings.load()
        hotel.name = "Hotel Demo Tirana"
        hotel.legal_name = "Hotel Demo Tirana sh.p.k."
        hotel.address = "Rruga e Durrësit, Tiranë"
        hotel.phone = "+355 4 000 0000"
        hotel.email = "info@example.com"
        hotel.setup_completed = True
        hotel.receipt_header = "Wi-Fi: HotelDemo · 08:00–23:00"
        hotel.max_staff_discount = 10
        hotel.save()

        users = {}
        for username, first, last, role in STAFF:
            u = User.objects.create_user(username, password=password, first_name=first, last_name=last, role=role)
            users[username] = u
        manager = users["manager"]

        types = {
            "SGL": RoomType.objects.create(
                name="Single", code="SGL", base_rate=Decimal("55"), max_adults=1, max_children=0
            ),
            "DBL": RoomType.objects.create(
                name="Double", code="DBL", base_rate=Decimal("75"), max_adults=2, max_children=1
            ),
            "TWN": RoomType.objects.create(
                name="Twin", code="TWN", base_rate=Decimal("75"), max_adults=2, max_children=1
            ),
            "STE": RoomType.objects.create(
                name="Suite", code="STE", base_rate=Decimal("140"), max_adults=3, max_children=2
            ),
        }
        layout = ["SGL", "DBL", "DBL", "TWN", "TWN", "STE"]
        rooms = []
        for floor in range(1, 5):
            for i, code in enumerate(layout, start=1):
                rooms.append(Room.objects.create(number=f"{floor}{i:02d}", room_type=types[code], floor=floor))

        outlets = {}
        for (name, kind, uses_tables, n_tables), cats in MENUS.items():
            outlet = Outlet.objects.create(name=name, kind=kind, uses_tables=uses_tables, sort_order=len(outlets))
            outlets[name] = outlet
            for t in range(1, n_tables + 1):
                zone = "Terrace" if t > 8 else "Inside"
                i = (t - 9) if t > 8 else (t - 1)
                Table.objects.create(
                    outlet=outlet,
                    name=str(t),
                    seats=2 if t % 3 == 0 else 4,
                    sort_order=t,
                    zone=zone if n_tables > 8 else "",
                    shape="round" if t % 3 == 0 else ("long" if t % 4 == 0 else "square"),
                    pos_x=80 + (i % 4) * 220,
                    pos_y=70 + (i // 4) * 250,
                    width=160 if t % 4 == 0 and t % 3 else 100,
                    height=100,
                )
            for c_order, (cat_name, items) in enumerate(cats.items()):
                cat = Category.objects.create(
                    outlet=outlet, name=CATEGORY_SQ.get(cat_name, cat_name), name_en=cat_name, sort_order=c_order
                )
                for i_order, item in enumerate(items):
                    Item.objects.create(
                        category=cat,
                        name=item[0],
                        price=Decimal(item[1]),
                        duration_minutes=item[2] if len(item) > 2 else None,
                        sort_order=i_order,
                    )

        guests = [
            Guest.objects.create(
                first_name=f, last_name=l, nationality=n, phone=f"+355 69 {random.randint(1000000, 9999999)}"
            )
            for f, l, n in GUESTS
        ]

        def book(guest, room, start_offset, nights, source=Reservation.Source.BOOKING_COM):
            res = Reservation(
                guest=guest,
                room=room,
                arrival=today + timedelta(days=start_offset),
                departure=today + timedelta(days=start_offset + nights),
                adults=1 if room.room_type.code == "SGL" else 2,
                rate=room.room_type.base_rate,
                source=source,
            )
            return fd.save_reservation(res, users["reception"])

        # In-house guests (arrived in the past few days)
        in_house = []
        for g, room, back, nights in [
            (guests[0], rooms[1], 2, 4),
            (guests[1], rooms[5], 1, 3),
            (guests[2], rooms[8], 3, 5),
            (guests[3], rooms[13], 0, 2),
        ]:
            res = book(g, room, -back, nights)
            Reservation.objects.filter(pk=res.pk).update(
                status=Reservation.Status.CHECKED_IN, checked_in_at=timezone.now()
            )
            res.refresh_from_db()
            fd.post_accommodation(res, None, today, night_audit=True)
            in_house.append(res)
        # A guest leaving today
        res = book(guests[4], rooms[2], -3, 3, Reservation.Source.PHONE)
        Reservation.objects.filter(pk=res.pk).update(status=Reservation.Status.CHECKED_IN, checked_in_at=timezone.now())
        # Arrivals today and upcoming
        book(guests[5], rooms[3], 0, 2)
        book(guests[6], rooms[15], 0, 4, Reservation.Source.WEBSITE)
        book(guests[7], rooms[20], 1, 3)
        book(guests[8], rooms[9], 2, 5, Reservation.Source.EXPEDIA)
        book(guests[9], rooms[17], 4, 7)
        # Some history, checked out last week
        for g, room in [(guests[10], rooms[6]), (guests[11], rooms[7])]:
            past = book(g, room, -9, 3, Reservation.Source.WALK_IN)
            Reservation.objects.filter(pk=past.pk).update(status=Reservation.Status.CHECKED_IN)
            past.refresh_from_db()
            fd.post_accommodation(past, manager, past.departure)
            fd.add_payment(past.folio, amount=past.folio.balance, method="card", user=users["reception"])
            Reservation.objects.filter(pk=past.pk).update(
                status=Reservation.Status.CHECKED_OUT, checked_out_at=timezone.now()
            )
            past.folio.status = "closed"
            past.folio.save()

        # Rooms needing work
        Room.objects.filter(pk__in=[rooms[4].pk, rooms[10].pk, rooms[19].pk]).update(hk_status=Room.HKStatus.DIRTY)

        # Outlet activity: a few paid orders, a room charge and open tables
        rest, bar, spa = outlets["Restaurant"], outlets["Lobby Bar"], outlets["Spa"]
        for table_no, picks in [(1, ["Tavë kosi", "Sallatë fshati", "Trilece"]), (4, ["Grilled sea bass", "Bakllava"])]:
            order = pos.open_order(rest, table=rest.tables.get(name=str(table_no)), user=users["waiter"], guests=2)
            for name in picks:
                pos.add_item(order, Item.objects.get(name=name, category__outlet=rest), user=users["waiter"])
            if table_no == 1:
                pos.pay_order(order, method="card", user=users["waiter"])
            else:
                pos.pay_order(order, method="cash", user=users["waiter"], tendered=Decimal("50"))
        order = pos.open_order(bar, table=bar.tables.get(name="2"), user=users["bar"])
        for name in ["Espresso", "Macchiato", "Fresh orange juice"]:
            pos.add_item(order, Item.objects.get(name=name), user=users["bar"])
        pos.charge_to_room(order, in_house[0], user=users["bar"])
        order = pos.open_order(spa, user=users["spa"], label=f"Room {in_house[1].room.number}")
        pos.add_item(order, Item.objects.get(name="Couples massage 80′"), user=users["spa"])
        pos.charge_to_room(order, in_house[1], user=users["spa"])
        # still open
        order = pos.open_order(rest, table=rest.tables.get(name="7"), user=users["waiter"], guests=3)
        for name in ["Fërgesë Tirane", "Fërgesë Tirane", "Byrek me spinaq"]:
            pos.add_item(order, Item.objects.get(name=name), user=users["waiter"])
        order = pos.open_order(bar, table=bar.tables.get(name="5"), user=users["bar"])
        pos.add_item(order, Item.objects.get(name="Birra Korça 0.5L"), user=users["bar"], quantity=2)

        # Housekeeping work for today
        for room in Room.objects.filter(hk_status=Room.HKStatus.DIRTY):
            HousekeepingTask.objects.create(
                room=room, kind=HousekeepingTask.Kind.DEPARTURE, created_by=manager, assigned_to=users["housekeeping"]
            )
        HousekeepingTask.objects.create(room=rooms[1], kind=HousekeepingTask.Kind.STAYOVER, created_by=manager)
        MaintenanceTicket.objects.create(
            title="Kondicioneri nuk ftoh",
            room=rooms[22],
            priority="high",
            reported_by=users["housekeeping"],
            blocks_room=True,
        )
        Room.objects.filter(pk=rooms[22].pk).update(out_of_order=True)

        # Some running costs
        for days_ago, cat, desc, supplier, amount, method in [
            (0, "food_drink", "Fruta & perime", "Tregu Elbasanit", "86.40", "cash"),
            (1, "supplies", "Detergjentë", "Big Market", "42.00", "card"),
            (3, "utilities", "Energji elektrike", "OSHEE", "380.00", "bank_transfer"),
            (5, "food_drink", "Kafe & sheqer", "Lavazza AL", "120.00", "bank_transfer"),
        ]:
            Expense.objects.create(
                business_date=today - timedelta(days=days_ago),
                category=cat,
                description=desc,
                supplier=supplier,
                amount=Decimal(amount),
                method=method,
                created_by=users["finance"],
            )

        self.stdout.write(self.style.SUCCESS("Demo hotel created."))
        self.stdout.write("Staff accounts (all use the same demo password):")
        for username, first, last, role in STAFF:
            self.stdout.write(f"  {username:<13} {role.label}")
        self.stdout.write(self.style.WARNING(f"Password: {password}"))
