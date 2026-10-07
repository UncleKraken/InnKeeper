# InnKeeper

**Hotel, restaurant, bar and services management — in one web app.**
Albanian and English. Runs on any device with a browser.

InnKeeper covers the whole property: the front desk, housekeeping, maintenance, and every place that sells something — restaurant, bar, café, spa, room service, minibar, laundry, transfers, events. Each sale is either paid on the spot or charged to the guest's room, and lands on one bill at check-out.

It adapts to the business: a setup wizard asks whether you run a **hotel**, a **guesthouse** or a **restaurant/bar/café**, and switches on only the parts you need.

> Version 2 is a complete rewrite. The original university project (CustomTkinter desktop app) is preserved on the [`uni-project`](https://github.com/UncleKraken/InnKeeper/tree/uni-project) branch.

---

## What it does

| Area | Highlights |
|---|---|
| **Front desk** | Room rack (calendar timeline), reservations with double-booking protection and room capacity checks, check-in / check-out, guest profiles with ID documents, booking sources (walk-in, phone, Booking.com, Airbnb…) |
| **Guest bill (folio)** | Room nights, extras and outlet charges in one place; cash / card / bank transfer payments; refunds; printable invoice; check-out blocked until the bill is settled (manager override for company invoices) |
| **Outlets (POS)** | Any number of outlets of any kind. Touch-friendly ordering, discounts with staff limits, split and mixed payments, cash change calculator, move/merge tables, charge to room, sold-out items |
| **Kitchen & bar** | Send orders to stations (Kitchen, Bar…); live kitchen display with sound, waiting time and Start → Ready; ready tables flagged on the waiter's floor plan; items removed after sending shown crossed out |
| **Printing** | ESC/POS thermal printers over the network (IP:9100) or installed in Windows; bills, receipts and kitchen tickets print directly; cash drawer kick; print log with retry |
| **Floor plans** | Drag-and-drop editor: move, resize, rename and renumber tables, square/round/long shapes, areas such as Inside and Terrace. The POS shows the real layout |
| **Receipts & menus** | Numbered receipts with logo, VAT breakdown and change, 58/80 mm thermal printing, receipt history with reprint and manager void. Guest menu on phones via QR code (Albanian/English), printable A4 menu and QR table cards |
| **Prices & online booking** | Seasons (percentage or fixed price per room type, minimum stay) priced night by night; public booking page (Albanian/English) with room photos, deposit by bank transfer, request → confirm/decline by reception, guest and staff emails over your own SMTP |
| **Groups & channels** | Group bookings (many rooms at once, one shared bill, bulk check-in/out); two-way calendar sync with Booking.com, Airbnb, Expedia via iCal links, with overbooking warnings; guest register for the authorities (print / Excel) |
| **Stock** | Stock items and suppliers, recipes per menu item (sales and room charges take stock automatically, voids put it back), deliveries with average cost and optional expense, waste, stock counts with variance, low-stock alerts, cost of sales report |
| **Housekeeping** | Room status board by floor, tasks created automatically at check-out, assign to staff, start → done |
| **Maintenance** | Tickets with priority and assignee; a ticket can take a room out of order until resolved |
| **Finance** | Revenue, expenses and profit; end-of-day cash count with printable Z report; best sellers, sales by staff and busiest hours; occupancy, ADR, RevPAR; unpaid bills; full ledger with CSV export (opens correctly in Excel) |
| **Settings** | Setup wizard, business details, receipt design with preview, modules on/off, staff and roles, activity log |
| **Backups** | Full backup (move to a new computer) and settings-only export (second location), restore with preview and automatic safety copy, daily automatic backups |
| **Help** | Built-in user guide in Albanian and English, getting-started checklist for new businesses |

### Security and data integrity
- Passwords hashed (Django PBKDF2); never shown, only replaced. Lockout after 5 failed sign-ins.
- Role-based access: Manager, Reception, Housekeeping, Maintenance, Service staff (optionally limited to specific outlets), Kitchen & bar (order screens only), Finance (also stock).
- Money is stored as exact decimals, never floats.
- Nothing financial is deleted. Mistakes are **voided** by a manager with a reason, and every action is written to the activity log.
- Bookings for the same room are serialised with a database lock, so two receptionists can't double-book a room at the same moment.
- CSRF protection, secure cookies and HSTS when served over HTTPS.

---

## Windows app

Download **InnKeeper-Setup-x.y.z.exe** from the [Releases page](https://github.com/UncleKraken/InnKeeper/releases) and run it. It adds an InnKeeper icon; opening it starts InnKeeper and opens it in your browser. On first start you create the manager account and the setup wizard does the rest.

- Data is kept in `%LOCALAPPDATA%\InnKeeper` (database, daily backups, logs), so updating or reinstalling never touches it.
- Other devices on the same Wi-Fi (tablets for waiters, a phone for housekeeping) open the address shown in the InnKeeper window.
- When a new version is published, managers see a notice in the app. Run the new installer; a backup is made automatically before the update.

The installer is built automatically by GitHub Actions (`.github/workflows/windows.yml`) on every push; pushing a tag such as `v2.1.0` publishes it as a release.

## Try it in 2 minutes (developers)

Requires Python 3.11+.

```bash
git clone https://github.com/UncleKraken/InnKeeper.git
cd InnKeeper
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
echo "DJANGO_DEBUG=1" > .env
python manage.py migrate
python manage.py seed_demo --password demo-pass-2026
python manage.py runserver
```

(Skip `seed_demo` to start empty: you'll be asked to create the first manager account and run the setup wizard.)

Open http://127.0.0.1:8000 and sign in as `manager`, `reception`, `housekeeping`, `maintenance`, `waiter`, `bar`, `spa` or `finance` (password `demo-pass-2026`). Each role sees only its own tools.

Run the tests with `python manage.py test`.

---

## Going live at a hotel

1. **Server.** Any small Linux server or a PC on the hotel network. Docker is the easiest route:
   ```bash
   cp .env.example .env        # set DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, POSTGRES_PASSWORD
   docker compose up -d
   ```
   This runs InnKeeper, PostgreSQL, and the nightly room-charge job. Open the site and create the first manager account.
2. **HTTPS.** Put it behind a reverse proxy (Caddy, Nginx, or Cloudflare Tunnel) with a certificate. On a closed office LAN without HTTPS, set `DJANGO_SECURE_SSL_REDIRECT=0`.
3. **Set up the business.** The setup wizard runs on first sign-in. Then follow the getting-started checklist on the dashboard.
4. **Nightly room charges.** `python manage.py night_audit` posts last night's room charge for every in-house guest, so revenue is reported on the right day. The Docker setup runs it at 03:00; otherwise schedule it with cron or Windows Task Scheduler. Check-out always posts any nights still missing, so a missed run never loses money.
5. **Channel calendars.** `python manage.py sync_calendars` reads the Booking.com / Airbnb calendars added under *Rooms & rates → Channels*. Docker runs it every 15 minutes, and so does the Windows app; elsewhere schedule it with cron. Channels can only read InnKeeper's room links if the site is reachable from the internet (set the public web address in Settings).
6. **Backups.** Schedule `python manage.py backup` daily (keeps the newest 30 in `INNKEEPER_BACKUP_DIR`) and copy them off the server. *Settings → Backup & restore* downloads or restores backups from the browser.

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
  inventory/       stock items, suppliers, recipes, deliveries, counts
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
- Full channel manager (rates and availability via OTA APIs, beyond calendar sync)
- Online card payments for deposits
- Purchase orders to suppliers
- Inventory and purchasing
