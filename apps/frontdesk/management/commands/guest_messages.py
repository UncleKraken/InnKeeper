from django.core.management.base import BaseCommand

from apps.frontdesk import guest_messages


class Command(BaseCommand):
    help = "Email guests their arrival information and review request when due (run every 15 minutes)."

    def handle(self, *args, **opts):
        self.stdout.write(f"{guest_messages.run()} message(s) sent.")
