"""
Guests' personal data: the privacy notice, erasing a guest on request, and (optionally) removing ID details
some years after the stay.

What stays: bills, receipts, fiscal invoices and payments. The law requires businesses to keep accounting
records, so those keep the name printed on them; everything else about the person is removed.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings, audit

from .models import Guest, Reservation, StayGuest


def _active(guest) -> bool:
    today = timezone.localdate()
    return guest.reservations.filter(
        status__in=[Reservation.Status.BOOKED, Reservation.Status.CHECKED_IN], departure__gte=today
    ).exists()


@transaction.atomic
def erase_guest(guest: Guest, user) -> None:
    """Remove a guest's personal details (on the guest's request). Bills and fiscal records stay."""
    if _active(guest):
        raise BusinessError(_("This guest has a current or upcoming stay. Erase the details after they leave."))
    email = guest.email
    guest.first_name = _("Erased")
    guest.last_name = _("guest") + f" #{guest.pk}"
    for field in ("email", "phone", "nationality", "document_type", "document_number", "address", "company", "notes"):
        setattr(guest, field, "")
    guest.date_of_birth = None
    guest.is_vip = False
    guest.save()
    StayGuest.objects.filter(reservation__guest=guest).update(
        document_type="", document_number="", date_of_birth=None, nationality=""
    )
    Reservation.objects.filter(guest=guest).update(notes="", arrival_time="")
    if email:
        from apps.marketing.models import Contact

        Contact.objects.filter(email__iexact=email).delete()
    audit(user, "guest.erased", f"#{guest.pk}", guest)


def remove_old_id_details(years: int | None = None) -> int:
    """Clear document numbers and dates of birth of guests whose last stay ended more than `years` ago."""
    years = HotelSettings.load().guest_id_keep_years if years is None else years
    if not years:
        return 0
    cutoff = timezone.localdate() - timedelta(days=365 * years + years // 4)
    old = (
        Guest.objects.annotate(last=Max("reservations__departure"))
        .filter(last__lt=cutoff)
        .exclude(document_number="", date_of_birth=None)
    )
    ids = list(old.values_list("pk", flat=True))
    if ids:
        Guest.objects.filter(pk__in=ids).update(document_type="", document_number="", date_of_birth=None)
    n_comp = (
        StayGuest.objects.filter(reservation__departure__lt=cutoff)
        .filter(~Q(document_number="") | Q(date_of_birth__isnull=False))
        .update(document_type="", document_number="", date_of_birth=None)
    )
    if ids or n_comp:
        audit(None, "guest.id_details_removed", f"{len(ids)} guest(s), {n_comp} companion(s), older than {years} years")
    return len(ids) + n_comp


@require_POST
@module_required("management")
def erase_view(request, pk):
    from django.contrib import messages

    guest = get_object_or_404(Guest, pk=pk)
    if request.POST.get("confirm") != "ERASE":
        messages.error(request, _("Type ERASE to confirm."))
        return redirect("frontdesk:guest_detail", pk=pk)
    try:
        erase_guest(guest, request.user)
    except BusinessError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, _("The guest's personal details were erased. Bills and fiscal records were kept."))
    return redirect("frontdesk:guest_detail", pk=pk)


def notice(request):
    """The public privacy notice (linked from booking and online check-in)."""
    from .public import _lang

    lang = _lang(request)
    return render(request, "booking/privacy.html", {"lang": lang, "custom": HotelSettings.load().privacy_notice.strip()})
