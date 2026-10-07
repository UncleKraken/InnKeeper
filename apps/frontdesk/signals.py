"""Tell the channel manager when availability or prices may have changed."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Reservation, Room, RoomType, SeasonRate


@receiver([post_save, post_delete], sender=Reservation)
@receiver([post_save, post_delete], sender=Room)
@receiver([post_save, post_delete], sender=RoomType)
@receiver([post_save, post_delete], sender=SeasonRate)
def availability_changed(sender, **kwargs):
    if kwargs.get("raw"):  # loading a backup
        return
    from .channex import mark_dirty

    mark_dirty()
