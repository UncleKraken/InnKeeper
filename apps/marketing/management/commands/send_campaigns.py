from django.core.management.base import BaseCommand

from apps.marketing.services import run_pending


class Command(BaseCommand):
    help = "Send campaign emails that are still waiting (run every 15 minutes)."

    def handle(self, *args, **opts):
        self.stdout.write(f"{run_pending(limit=500)} email(s) sent.")
