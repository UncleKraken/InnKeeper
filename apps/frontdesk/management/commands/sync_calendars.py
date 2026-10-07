from django.core.management.base import BaseCommand

from apps.frontdesk.ical import sync_all


class Command(BaseCommand):
    help = "Read the Booking.com / Airbnb / … calendars added under Rooms & rates → Calendar links. Run every 15–30 minutes."

    def handle(self, *args, **opts):
        for feed, r in sync_all().items():
            if r.error:
                self.stderr.write(f"{feed}: {r.error}")
            else:
                self.stdout.write(
                    f"{feed}: +{r.created} ~{r.updated} -{r.cancelled}"
                    + (f", {len(r.conflicts)} conflict(s)" if r.conflicts else "")
                )
