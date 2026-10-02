from django.core.management.base import BaseCommand

from apps.core.backup import save_backup_to_disk


class Command(BaseCommand):
    help = "Save a full backup into the backup folder. Schedule daily; keeps the newest N files."

    def add_arguments(self, parser):
        parser.add_argument("--keep", type=int, default=30, help="How many automatic backups to keep (default 30).")

    def handle(self, *args, **opts):
        path = save_backup_to_disk("auto", keep=opts["keep"])
        self.stdout.write(self.style.SUCCESS(f"Backup saved: {path}"))
