from django.core.management.base import BaseCommand

from apps.core import sync


class Command(BaseCommand):
    help = "Copy all data to the folder set in Settings → Backup (when a copy is due). Run every few minutes."

    def add_arguments(self, parser):
        parser.add_argument("--now", action="store_true", help="Copy now, even if one isn't due.")

    def handle(self, *args, now=False, **options):
        try:
            path = sync.run(force=now)
        except sync.SyncError as e:
            self.stderr.write(f"Copy failed: {e}")
            raise SystemExit(1)
        if path:
            self.stdout.write(f"Copy saved: {path}")
