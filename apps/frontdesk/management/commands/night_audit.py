from datetime import date

from django.core.management.base import BaseCommand

from apps.frontdesk.services import night_audit


class Command(BaseCommand):
    help = "Post last night's room charge to every in-house guest's bill. Schedule daily, e.g. at 03:00."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Run as if today were YYYY-MM-DD (for catching up).")

    def handle(self, *args, **options):
        on_date = date.fromisoformat(options["date"]) if options.get("date") else None
        count = night_audit(on_date)
        self.stdout.write(self.style.SUCCESS(f"Posted room charges for {count} stay(s)."))
