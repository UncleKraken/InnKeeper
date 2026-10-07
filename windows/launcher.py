"""
InnKeeper for Windows.

Starts InnKeeper on this computer and opens it in the browser. A small window
shows the address other devices on the same network can use, with buttons to
open InnKeeper, open the backups folder, and stop.

Data lives in %LOCALAPPDATA%\\InnKeeper (database, backups, logs), so updating
or reinstalling the app never touches it.

Run with --selftest to start, check /health/, and exit (used by the build).
"""

import os
import secrets
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

APP_NAME = "InnKeeper"
PORT = int(os.environ.get("INNKEEPER_PORT", "8765"))


def app_root() -> Path:
    # PyInstaller unpacks into sys._MEIPASS; in development this file lives in windows/.
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(os.environ.get("INNKEEPER_DATA_DIR", Path(base) / APP_NAME))
    (path / "backups").mkdir(parents=True, exist_ok=True)
    (path / "logs").mkdir(parents=True, exist_ok=True)
    return path


def configure_environment(data: Path) -> None:
    key_file = data / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(50), encoding="utf-8")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ["DJANGO_DEBUG"] = "0"
    os.environ["DJANGO_SECRET_KEY"] = key_file.read_text(encoding="utf-8").strip()
    os.environ["DATABASE_URL"] = "sqlite:///" + str(data / "innkeeper.sqlite3").replace("\\", "/")
    os.environ["INNKEEPER_BACKUP_DIR"] = str(data / "backups")
    os.environ["DJANGO_ALLOWED_HOSTS"] = "*"
    os.environ["DJANGO_SECURE_SSL_REDIRECT"] = "0"
    os.environ["DJANGO_SECURE_COOKIES"] = "0"
    sys.path.insert(0, str(app_root()))


def lan_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def already_running() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health/", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def prepare_database(log) -> None:
    import django
    from django.core.management import call_command

    django.setup()
    from django.db import connection

    from apps import __version__
    from apps.core.backup import save_backup_to_disk

    data = data_dir()
    version_file = data / "version.txt"
    db_exists = (data / "innkeeper.sqlite3").exists()
    previous = version_file.read_text().strip() if version_file.exists() else ""
    if db_exists and previous and previous != __version__:
        # An update: keep a copy of the data from before migrating.
        try:
            path = save_backup_to_disk(f"before-update-{previous}", keep=5)
            log(f"Backup before update: {path.name}")
        except Exception as e:  # an unreadable old database shouldn't block startup
            log(f"Backup before update failed: {e}")
    call_command("migrate", interactive=False, verbosity=0)
    with connection.cursor() as c:
        c.execute("PRAGMA journal_mode=WAL;")  # better with several devices at once
    version_file.write_text(__version__)
    log(f"Database ready (version {__version__}).")


def daily_jobs(log, stop: threading.Event) -> None:
    """Daily automatic backup, the nightly room-charge posting and channel calendar sync (every 15 minutes)."""
    from django.utils import timezone

    from apps.core.backup import backup_dir, save_backup_to_disk
    from apps.frontdesk.services import night_audit

    state = data_dir() / "last_audit.txt"
    while not stop.is_set():
        try:
            autos = sorted(backup_dir().glob("auto-*.innkeeper"), key=lambda p: p.stat().st_mtime)
            if not autos or datetime.fromtimestamp(autos[-1].stat().st_mtime) < datetime.now() - timedelta(hours=20):
                save_backup_to_disk("auto", keep=30)
                log("Daily backup saved.")
            today = timezone.localdate().isoformat()
            if timezone.localtime().hour >= 3 and (not state.exists() or state.read_text().strip() != today):
                n = night_audit()
                state.write_text(today)
                log(f"Room charges posted for {n} stay(s).")
        except Exception as e:
            log(f"Daily job error: {e}")
        try:
            from apps.frontdesk.ical import sync_all

            for feed, r in sync_all().items():
                if r.error or r.created or r.updated or r.cancelled or r.conflicts:
                    log(f"Calendar {feed}: +{r.created} ~{r.updated} -{r.cancelled} {r.error}")
        except Exception as e:
            log(f"Calendar sync error: {e}")
        stop.wait(900)


def channel_jobs(log, stop: threading.Event) -> None:
    """Channel manager (Channex): new bookings every minute, availability and prices when they change,
    and a full refresh every night."""
    from apps.core.models import HotelSettings
    from apps.frontdesk.channex import sync

    last_full = None
    while not stop.is_set():
        try:
            if HotelSettings.objects.filter(pk=1, channex_enabled=True).exists():
                today = datetime.now().date()
                r = sync(force_push=last_full != today)
                last_full = today if not r["error"] else last_full
                if r["error"] or r["bookings"]:
                    log(f"Channel manager: {r['bookings']} booking update(s) {r['error']}")
        except Exception as e:
            log(f"Channel manager error: {e}")
        stop.wait(60)


def serve(log, ready: threading.Event) -> None:
    from waitress import serve as waitress_serve

    from config.wsgi import application

    ready.set()
    waitress_serve(application, host="0.0.0.0", port=PORT, threads=8, ident=APP_NAME, _quiet=True)


def run_selftest() -> int:
    data = data_dir()
    configure_environment(data)
    prepare_database(print)
    ready = threading.Event()
    threading.Thread(target=serve, args=(print, ready), daemon=True).start()
    ready.wait(30)
    for _ in range(30):
        if already_running():
            print("SELFTEST OK")
            return 0
        time.sleep(1)
    print("SELFTEST FAILED")
    return 1


def main() -> int:
    # A windowed .exe has no console; give Python somewhere harmless to write.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115
    if "--selftest" in sys.argv:
        out = data_dir() / "logs" / "selftest.txt"
        sys.stdout = sys.stderr = out.open("w", encoding="utf-8")
        try:
            return run_selftest()
        except BaseException:
            import traceback

            traceback.print_exc()
            return 1
        finally:
            sys.stdout.flush()

    local_url = f"http://localhost:{PORT}/"
    if already_running():
        webbrowser.open(local_url)
        return 0

    data = data_dir()
    log_file = (data / "logs" / f"{datetime.now():%Y-%m}.log").open("a", encoding="utf-8")
    lines: list[str] = []

    def log(msg: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
        lines.append(line)
        log_file.write(line + "\n")
        log_file.flush()

    configure_environment(data)
    try:
        prepare_database(log)
    except Exception as e:
        log(f"Could not prepare the database: {e}")
        raise

    stop = threading.Event()
    ready = threading.Event()
    threading.Thread(target=serve, args=(log, ready), daemon=True).start()
    threading.Thread(target=daily_jobs, args=(log, stop), daemon=True).start()
    threading.Thread(target=channel_jobs, args=(log, stop), daemon=True).start()
    ready.wait(30)
    for _ in range(40):
        if already_running():
            break
        time.sleep(0.25)
    lan_url = f"http://{lan_address()}:{PORT}/"
    log(f"Running at {local_url} and {lan_url}")
    webbrowser.open(local_url)

    try:
        import tkinter as tk
    except ImportError:  # no GUI available: keep serving until interrupted
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("440x260")
    root.resizable(False, False)
    root.configure(bg="#16202f")
    ico = app_root() / "windows" / "innkeeper.ico"
    if ico.exists():
        try:
            root.iconbitmap(str(ico))
        except tk.TclError:
            pass

    def label(text, size=10, bold=False, fg="#dfe5ee", pady=2):
        w = tk.Label(root, text=text, bg="#16202f", fg=fg, font=("Segoe UI", size, "bold" if bold else "normal"))
        w.pack(pady=pady)
        return w

    label("InnKeeper", 16, True, "#ffffff", (16, 2))
    label("InnKeeper po punon · is running", 10, False, "#b9c3d2")
    label("Në këtë kompjuter · On this computer:", 9, False, "#7d8899", (12, 0))
    label(local_url, 11, True, "#d9b679", 0)
    label("Pajisjet e tjera në Wi-Fi · Other devices on Wi-Fi:", 9, False, "#7d8899", (8, 0))
    label(lan_url, 11, True, "#d9b679", 0)

    bar = tk.Frame(root, bg="#16202f")
    bar.pack(pady=16)

    def button(text, cmd, primary=False):
        tk.Button(
            bar,
            text=text,
            command=cmd,
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            bg="#0e6e64" if primary else "#2f3d52",
            fg="#ffffff",
            activebackground="#0a5a52",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=4)

    def quit_app():
        stop.set()
        root.destroy()

    button("Hap · Open", lambda: webbrowser.open(local_url), True)
    button("Kopjet rezervë · Backups", lambda: os.startfile(str(data / "backups")))  # noqa: S606
    button("Ndalo · Stop", quit_app)
    root.protocol("WM_DELETE_WINDOW", root.iconify)  # closing the window keeps InnKeeper running
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
