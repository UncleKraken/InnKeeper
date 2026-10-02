# InnKeeper

**Hotel, restaurant, bar and services management — in one web app.**
Albanian and English. Runs on any device with a browser.

InnKeeper covers the whole property: the front desk, housekeeping, maintenance, and every place that sells something — restaurant, bar, café, spa, room service, minibar, laundry, transfers, events. Each sale is either paid on the spot or charged to the guest's room, and lands on one bill at check-out.

> Version 2 is a complete rewrite. The original university project (CustomTkinter desktop app) is preserved on the `master` branch.

---

## What it does

| Area | Highlights |
|---|---|
| **Front desk** | Room rack (calendar timeline), reservations with double-booking protection and room capacity checks, check-in / check-out, guest profiles with ID documents, booking sources (walk-in, phone, Booking.com, Airbnb…) |
| **Guest bill (folio)** | Room nights, extras and outlet charges in one place; cash / card / bank transfer payments; refunds; printable invoice; check-out blocked until the bill is settled (manager override for company invoices) |
| **Outlets** | Any number of outlets of any kind. Tables or no tables, categories, items and services (with duration for spa treatments), touch-friendly POS, pay or charge to room, printable receipts |
| **Housekeeping** | Room status board by floor, tasks created automatically at check-out, assign to staff, start → done |
| **Maintenance** | Tickets with priority and assignee; a ticket can take a room out of order until resolved |
| **Finance** | Revenue by day and by department, payments by method, occupancy, ADR, RevPAR, unpaid bills, full ledger with CSV export (opens correctly in Excel) |
| **Management** | Rooms & rates, outlets & menus, staff accounts and roles, hotel details for invoices, activity log of every check-in, payment and void |

### Security and data integrity
- Passwords hashed (Django PBKDF2); never shown, only replaced. Lockout after 5 failed sign-ins.
- Role-based access: Manager, Reception, Housekeeping, Maintenance, Service staff (optionally limited to specific outlets), Finance.
- Money is stored as exact decimals, never floats.
- Nothing financial is deleted. Mistakes are **voided** by a manager with a reason, and every action is written to the activity log.
- Bookings for the same room are serialised with a database lock, so two receptionists can't double-book a room at the same moment.
- CSRF protection, secure cookies and HSTS when served over HTTPS.

---

## Try it in 2 minutes

Requires Python 3.11+.

```bash
git clone https://github.com/UncleKraken/InnKeeper.git
cd InnKeeper
git checkout v2
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
echo "DJANGO_DEBUG=1" > .env
python manage.py migrate
python manage.py seed_demo --password demo-pass-2026
python manage.py runserver
```

Open http://127.0.0.1:8000 and sign in as `manager`, `reception`, `housekeeping`, `maintenance`, `waiter`, `bar`, `spa` or `finance` (password `demo-pass-2026`). Each role sees only its own tools.

Run the tests with `python manage.py test`.

---

## Going live at a hotel

1. **Server.** Any small Linux server or a PC on the hotel network. Docker is the easiest route:
   ```bash
   cp .env.example .env        # set DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, POSTGRES_PASSWORD
   docker compose up -d
   docker compose exec web python manage.py createsuperuser
   ```
   This runs InnKeeper, PostgreSQL, and the nightly room-charge job.
2. **HTTPS.** Put it behind a reverse proxy (Caddy, Nginx, or Cloudflare Tunnel) with a certificate. On a closed office LAN without HTTPS, set `DJANGO_SECURE_SSL_REDIRECT=0`.
3. **Set up the hotel.** Sign in as the superuser → *Hotel settings* (name, NIPT, address, currency, VAT) → *Rooms & rates* → *Outlets & menus* → *Staff*.
4. **Nightly room charges.** `python manage.py night_audit` posts last night's room charge for every in-house guest, so revenue is reported on the right day. The Docker setup runs it at 03:00; otherwise schedule it with cron or Windows Task Scheduler. Check-out always posts any nights still missing, so a missed run never loses money.
5. **Backups.** Back up the database daily and keep copies off the server, e.g. `docker compose exec db pg_dump -U innkeeper innkeeper > backup-$(date +%F).sql`.

`/admin/` (Django admin) is available to superusers for advanced fixes; the ledger is read-only there.

### Before using it for real money in Albania
- **Fiscalisation.** Albanian law requires sales to be fiscalised through the tax authority (e-invoices / fiscal receipts with NIVF/NSLF codes). InnKeeper prints internal receipts and invoices; integration with a certified fiscal service or device is **not** included yet and is required before replacing a fiscal cash register.
- **Personal data.** Guest IDs and contact details are personal data under Law 124/2024 on personal data protection. Limit staff access, keep backups secure, and set a retention period.

---

## Project layout

```
config/            settings, URLs, WSGI
apps/
  core/            hotel settings, dashboard, activity log, shared UI helpers
  accounts/        staff, roles, sign-in, permissions
  frontdesk/       room types, rooms, guests, reservations, invoices
  housekeeping/    room status, cleaning tasks, maintenance tickets
  outlets/         restaurant/bar/spa/… menus, tables, orders, POS
  finance/         folios, charges, payments, reports
templates/         HTML templates (one folder per app)
static/            CSS and icons (no build step, works offline)
locale/sq/         Albanian translations
```

Business rules live in each app's `services.py` (e.g. `frontdesk/services.py: check_out`), so views stay thin and the rules are tested directly.

### Translations
Interface text is in English in the code and translated in `locale/sq/LC_MESSAGES/django.po`. After changing text:
```bash
python manage.py makemessages -l sq
# edit django.po
python manage.py compilemessages
```
Each user can switch language (SQ / EN) from the sidebar; the choice is remembered.

## Roadmap
- Fiscal receipt / e-invoice integration (Albania)
- Channel manager sync (Booking.com, Airbnb) and an online booking page
- Rate plans and seasons, deposits, group bookings
- Kitchen / bar order display
- Inventory and purchasing
- Guest registration export for the authorities
