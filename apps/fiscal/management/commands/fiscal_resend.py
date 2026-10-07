from django.core.management.base import BaseCommand

from apps.fiscal.services import resend_pending


class Command(BaseCommand):
    help = "Send fiscal documents that couldn't reach the tax authority earlier. Run every minute."

    def handle(self, *args, **opts):
        self.stdout.write(f"sent: {resend_pending()}")
