from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class HousekeepingTask(models.Model):
    class Kind(models.TextChoices):
        DEPARTURE = "departure", _("Departure clean")
        STAYOVER = "stayover", _("Stay-over service")
        DEEP = "deep", _("Deep clean")
        TURNDOWN = "turndown", _("Turndown")
        INSPECTION = "inspection", _("Inspection")

    class Status(models.TextChoices):
        PENDING = "pending", _("To do")
        IN_PROGRESS = "in_progress", _("In progress")
        DONE = "done", _("Done")

    room = models.ForeignKey(
        "frontdesk.Room", on_delete=models.CASCADE, related_name="hk_tasks", verbose_name=_("room")
    )
    kind = models.CharField(_("type"), max_length=12, choices=Kind.choices, default=Kind.DEPARTURE)
    status = models.CharField(_("status"), max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hk_tasks",
        verbose_name=_("assigned to"),
    )
    due_date = models.DateField(_("due date"), default=timezone.localdate)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = _("housekeeping task")
        verbose_name_plural = _("housekeeping tasks")
        ordering = ["status", "due_date", "room__floor", "room__number"]

    def __str__(self) -> str:
        return f"{self.room} · {self.get_kind_display()}"


class MaintenanceTicket(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("High")
        URGENT = "urgent", _("Urgent")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        IN_PROGRESS = "in_progress", _("In progress")
        RESOLVED = "resolved", _("Resolved")

    room = models.ForeignKey(
        "frontdesk.Room",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
        verbose_name=_("room"),
    )
    location = models.CharField(
        _("location"), max_length=120, blank=True, help_text=_("If not a room, e.g. Lobby, Pool, Kitchen.")
    )
    title = models.CharField(_("problem"), max_length=160)
    description = models.TextField(_("details"), blank=True)
    priority = models.CharField(_("priority"), max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(_("status"), max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    blocks_room = models.BooleanField(
        _("room out of order"), default=False, help_text=_("The room cannot be sold until this is resolved.")
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
        verbose_name=_("assigned to"),
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(_("resolution"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("maintenance ticket")
        verbose_name_plural = _("maintenance tickets")
        ordering = ["status", "-created_at"]

    def __str__(self) -> str:
        return self.title

    @property
    def where(self) -> str:
        if self.room_id:
            return _("Room %(n)s") % {"n": self.room.number}
        return self.location or "—"
