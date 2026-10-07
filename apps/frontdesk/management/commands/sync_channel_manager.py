from django.core.management.base import BaseCommand

from apps.frontdesk.channex import sync


class Command(BaseCommand):
    help = "Fetch new bookings from the channel manager (Channex) and send availability and prices. Run every minute."

    def add_arguments(self, parser):
        parser.add_argument(
            "--full", action="store_true", help="Send all availability and prices even if nothing changed."
        )

    def handle(self, *args, **opts):
        r = sync(force_push=opts["full"])
        if r["error"]:
            self.stderr.write(r["error"])
        else:
            self.stdout.write(f"bookings: {r['bookings']}, sent: {'yes' if r['pushed'] else 'no change'}")
