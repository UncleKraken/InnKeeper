from datetime import date

from django.core.management.base import BaseCommand

from apps.finance import summary


class Command(BaseCommand):
    help = "Email the owner's daily summary when it is due (run every 15 minutes), or for --date now."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Send the summary of this business day now (YYYY-MM-DD).")

    def handle(self, *args, **opts):
        if opts["date"]:
            ok = summary.send(date.fromisoformat(opts["date"]), force=True)
        else:
            ok = summary.run()
        self.stdout.write("Summary sent." if ok else "Nothing sent.")
