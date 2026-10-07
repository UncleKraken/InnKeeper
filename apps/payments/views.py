from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.exceptions import BusinessError
from apps.core.models import HotelSettings
from apps.frontdesk.models import Reservation

from . import services
from .models import PaymentLink
from .providers import Paysera, Pok, ProviderError, get_provider


def _lang(request):
    lang = request.GET.get("lang") or translation.get_language() or "sq"
    lang = "en" if lang.startswith("en") else "sq"
    translation.activate(lang)
    return lang


# ---------- Guest pages (no login) ----------


def pay(request, token):
    link = get_object_or_404(PaymentLink.objects.select_related("reservation__guest", "reservation__room"), token=token)
    lang = _lang(request)
    error = ""
    if request.method == "POST" and link.is_open:
        try:
            return redirect(services.start_checkout(link, request.build_absolute_uri("/"), lang))
        except BusinessError as e:
            error = str(e)
    return render(
        request,
        "payments/pay.html",
        {"link": link, "lang": lang, "error": error, "cancelled": request.GET.get("cancelled") == "1"},
    )


def done(request, token):
    """Where the provider sends the guest back. For POK we ask POK directly; Paysera tells us by callback."""
    link = get_object_or_404(PaymentLink, token=token)
    _lang(request)
    if link.is_open and link.provider == "pok" and link.external_id:
        provider = get_provider(HotelSettings.load())
        if isinstance(provider, Pok):
            try:
                link = services.record_result(link, provider.check(link.external_id), source="return")
            except ProviderError:
                pass
    return render(request, "payments/done.html", {"link": link})


@csrf_exempt
@require_POST
def pok_webhook(request, token):
    link = PaymentLink.objects.filter(token=token, provider="pok").first()
    if link is None or not link.external_id:
        raise Http404
    provider = get_provider(HotelSettings.load())
    if not isinstance(provider, Pok):
        return HttpResponseBadRequest("not configured")
    try:
        # The webhook body is not trusted: read the order back from POK.
        services.record_result(link, provider.check(link.external_id), source="webhook")
    except ProviderError as e:
        return HttpResponse(f"retry: {e}", status=502)
    return HttpResponse("OK")


@csrf_exempt
def paysera_callback(request):
    params = request.POST if request.method == "POST" else request.GET
    provider = get_provider(HotelSettings.load())
    if not isinstance(provider, Paysera):
        return HttpResponseBadRequest("not configured")
    try:
        data, result = provider.parse_callback(params.get("data", ""), params.get("ss1", ""))
    except ProviderError:
        return HttpResponseBadRequest("bad request")
    link = PaymentLink.objects.filter(token=data.get("orderid", ""), provider="paysera").first()
    if link is None:
        return HttpResponseBadRequest("unknown order")
    if data.get("test") == "1" and not link.test_mode:
        return HttpResponseBadRequest("test payment for a live link")
    services.record_result(link, result, source="callback")
    return HttpResponse("OK")  # Paysera expects exactly this


# ---------- Staff ----------


@require_POST
@module_required("frontdesk")
def create_for_reservation(request, pk):
    res = get_object_or_404(Reservation.objects.select_related("guest"), pk=pk)
    try:
        amount = Decimal(request.POST.get("amount", "").replace(",", "."))
    except InvalidOperation:
        messages.error(request, _("Enter an amount above zero."))
        return redirect("frontdesk:reservation_detail", pk=pk)
    try:
        link = services.create_link(
            reservation=res,
            amount=amount,
            purpose=request.POST.get("purpose", PaymentLink.Purpose.BALANCE),
            user=request.user,
            email_to=request.POST.get("email", "").strip(),
        )
    except BusinessError as e:
        messages.error(request, str(e))
        return redirect("frontdesk:reservation_detail", pk=pk)
    if request.POST.get("send") == "1":
        if services.send_link_email(link, request.build_absolute_uri("/")):
            messages.success(request, _("Payment link sent to %(email)s.") % {"email": link.email})
        else:
            messages.warning(request, _("The link was created but could not be emailed. Copy it from the list."))
    else:
        messages.success(request, _("Payment link created. Copy it and send it to the guest."))
    return redirect("frontdesk:reservation_detail", pk=pk)


@require_POST
@module_required("frontdesk")
def link_action(request, pk):
    link = get_object_or_404(PaymentLink, pk=pk)
    action = request.POST.get("action")
    try:
        if action == "cancel":
            services.cancel_link(link, request.user)
        elif action == "paid":
            services.mark_paid_by_hand(link, request.user)
        elif action == "check":
            provider = get_provider(HotelSettings.load())
            if isinstance(provider, Pok) and link.external_id:
                link = services.record_result(link, provider.check(link.external_id), source="check")
                if link.status != PaymentLink.Status.PAID:
                    messages.info(request, _("Not paid yet."))
        elif action == "send":
            if services.send_link_email(link, request.build_absolute_uri("/")):
                messages.success(request, _("Payment link sent to %(email)s.") % {"email": link.email})
            else:
                messages.error(request, _("No email address, or email is not set up."))
    except (BusinessError, ProviderError) as e:
        messages.error(request, str(e))
    if link.reservation_id:
        return redirect("frontdesk:reservation_detail", pk=link.reservation_id)
    return redirect("core:dashboard")
