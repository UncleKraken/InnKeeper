from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import BusinessError
from apps.core.models import audit
from apps.frontdesk.models import Room

from .models import HousekeepingTask, MaintenanceTicket

CLEANING_KINDS = {
    HousekeepingTask.Kind.DEPARTURE,
    HousekeepingTask.Kind.STAYOVER,
    HousekeepingTask.Kind.DEEP,
}


def room_vacated(room: Room, user) -> HousekeepingTask:
    """Called at check-out: the room becomes dirty and a departure clean is queued."""
    Room.objects.filter(pk=room.pk).update(hk_status=Room.HKStatus.DIRTY)
    task, _created = HousekeepingTask.objects.get_or_create(
        room=room,
        kind=HousekeepingTask.Kind.DEPARTURE,
        status=HousekeepingTask.Status.PENDING,
        defaults={"created_by": user, "due_date": timezone.localdate()},
    )
    return task


@transaction.atomic
def set_room_status(room: Room, status: str, user) -> Room:
    if status not in Room.HKStatus.values:
        raise BusinessError(_("Unknown room status."))
    room = Room.objects.select_for_update().get(pk=room.pk)
    room.hk_status = status
    room.save(update_fields=["hk_status"])
    if status in (Room.HKStatus.CLEAN, Room.HKStatus.INSPECTED):
        now = timezone.now()
        open_kinds = CLEANING_KINDS | (
            {HousekeepingTask.Kind.INSPECTION} if status == Room.HKStatus.INSPECTED else set()
        )
        room.hk_tasks.exclude(status=HousekeepingTask.Status.DONE).filter(kind__in=open_kinds).update(
            status=HousekeepingTask.Status.DONE, completed_at=now, completed_by=user
        )
    audit(user, "room.status", f"{room.number} → {room.get_hk_status_display()}", room)
    return room


@transaction.atomic
def advance_task(task: HousekeepingTask, user) -> HousekeepingTask:
    """To do → In progress → Done. Finishing a cleaning task makes the room clean."""
    task = HousekeepingTask.objects.select_for_update().select_related("room").get(pk=task.pk)
    now = timezone.now()
    if task.status == HousekeepingTask.Status.PENDING:
        task.status = HousekeepingTask.Status.IN_PROGRESS
        task.started_at = now
        if task.assigned_to_id is None and user.role == "housekeeping":
            task.assigned_to = user
        task.save()
        return task
    if task.status == HousekeepingTask.Status.IN_PROGRESS:
        task.status = HousekeepingTask.Status.DONE
        task.completed_at = now
        task.completed_by = user
        task.save()
        if task.kind in CLEANING_KINDS:
            Room.objects.filter(pk=task.room_id).update(hk_status=Room.HKStatus.CLEAN)
        elif task.kind == HousekeepingTask.Kind.INSPECTION:
            Room.objects.filter(pk=task.room_id).update(hk_status=Room.HKStatus.INSPECTED)
        audit(user, "hk.task_done", f"{task}", task)
        return task
    raise BusinessError(_("This task is already done."))


def _sync_room_out_of_order(room: Room) -> None:
    blocked = room.tickets.filter(blocks_room=True).exclude(status=MaintenanceTicket.Status.RESOLVED).exists()
    if room.out_of_order != blocked:
        fields = {"out_of_order": blocked}
        if not blocked:
            fields["hk_status"] = Room.HKStatus.DIRTY  # needs a check after repair work
        Room.objects.filter(pk=room.pk).update(**fields)


@transaction.atomic
def save_ticket(ticket: MaintenanceTicket, user) -> MaintenanceTicket:
    is_new = ticket.pk is None
    if is_new:
        ticket.reported_by = user
    if ticket.blocks_room and not ticket.room_id:
        raise BusinessError(_("Choose a room to mark it out of order."))
    ticket.save()
    if ticket.room_id:
        _sync_room_out_of_order(ticket.room)
    audit(user, "ticket.create" if is_new else "ticket.update", ticket.title, ticket)
    return ticket


@transaction.atomic
def resolve_ticket(ticket: MaintenanceTicket, user, resolution: str = "") -> MaintenanceTicket:
    ticket = MaintenanceTicket.objects.select_for_update().get(pk=ticket.pk)
    if ticket.status == MaintenanceTicket.Status.RESOLVED:
        raise BusinessError(_("Already resolved."))
    ticket.status = MaintenanceTicket.Status.RESOLVED
    ticket.resolved_at = timezone.now()
    ticket.resolution = resolution[:255]
    ticket.save()
    if ticket.room_id:
        _sync_room_out_of_order(ticket.room)
    audit(user, "ticket.resolve", ticket.title, ticket)
    return ticket
