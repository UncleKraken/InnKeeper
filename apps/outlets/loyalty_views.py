"""Till actions for loyalty cards, and the pages for gift vouchers and loyalty cards."""

from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.exceptions import BusinessError
from apps.core.forms import StyledFormMixin
from apps.core.models import HotelSettings
from apps.finance import loyalty
from apps.finance.models import GiftVoucher, LoyaltyCard, Payment

from .views import _back_to_order, _order_for


@require_POST
@module_required("outlets")
def attach_card(request, pk):
    order = _order_for(request, pk)
    try:
        name = request.POST.get("name", "").strip()
        if name:
            card = loyalty.create_card(name=name, phone=request.POST.get("phone", ""))
            messages.success(request, _("New loyalty card %(n)s for %(name)s.") % {"n": card.number, "name": card.name})
        else:
            card = loyalty.find_card(request.POST.get("q", ""))
            if card is None:
                raise BusinessError(_("No loyalty card with that phone or number. Add a new card below."))
        loyalty.attach_card(order, card, request.user)
    except BusinessError as e:
        messages.error(request, str(e))
    return _back_to_order(order)


@require_POST
@module_required("outlets")
def card_reward(request, pk):
    order = _order_for(request, pk)
    try:
        free = loyalty.give_reward(order, request.user)
        messages.success(request, _("Free item from the loyalty card: −%(a)s.") % {"a": f"{free:.2f}"})
    except BusinessError as e:
        messages.error(request, str(e))
    return _back_to_order(order)


@require_POST
@module_required("outlets")
def detach_card(request, pk):
    order = _order_for(request, pk)
    if order.is_open and not order.loyalty_reward:
        type(order).objects.filter(pk=order.pk).update(loyalty_card=None)
    return _back_to_order(order)


# ---------- Gift vouchers ----------


class SellVoucherForm(StyledFormMixin, forms.Form):
    amount = forms.DecimalField(label=gettext_lazy("Value"), min_value=Decimal("0.01"), decimal_places=2)
    method = forms.ChoiceField(
        label=gettext_lazy("Paid with"),
        choices=[(Payment.Method.CASH, gettext_lazy("Cash")), (Payment.Method.CARD, gettext_lazy("Card")), (Payment.Method.BANK_TRANSFER, gettext_lazy("Bank transfer"))],
    )
    buyer = forms.CharField(label=gettext_lazy("Bought by"), max_length=120, required=False)
    note = forms.CharField(label=gettext_lazy("Note"), max_length=255, required=False, help_text=gettext_lazy("e.g. who it is for"))


@module_required("outlets")
def vouchers(request):
    hs = HotelSettings.load()
    form = SellVoucherForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            v = loyalty.sell_voucher(user=request.user, **form.cleaned_data)
            messages.success(request, _("Gift voucher %(code)s sold. Print it for the customer.") % {"code": v.code})
            return redirect("outlets:voucher", pk=v.pk)
        except BusinessError as e:
            messages.error(request, str(e))
    found = None
    q = request.GET.get("q", "").strip()
    if q:
        try:
            found = loyalty.find_voucher(q)
            return redirect("outlets:voucher", pk=found.pk)
        except BusinessError as e:
            messages.error(request, str(e))
    page = Paginator(GiftVoucher.objects.select_related("created_by"), 50).get_page(request.GET.get("page"))
    return render(request, "outlets/vouchers.html", {"form": form, "page_obj": page, "q": q, "enabled": hs.vouchers_enabled})


@module_required("outlets")
def voucher(request, pk):
    v = get_object_or_404(GiftVoucher, pk=pk)
    if request.method == "POST" and request.POST.get("void") == "1":
        try:
            loyalty.void_voucher(v, user=request.user, reason=request.POST.get("reason", ""))
            messages.success(request, _("Gift voucher voided. Give the money back to the customer."))
        except BusinessError as e:
            messages.error(request, str(e))
        return redirect("outlets:voucher", pk=v.pk)
    uses = v.payments.filter(method=Payment.Method.VOUCHER).select_related("order__outlet").order_by("created_at")
    sale = v.payments.exclude(method=Payment.Method.VOUCHER).first()
    return render(request, "outlets/voucher.html", {"v": v, "uses": uses, "sale": sale, "print_mode": request.GET.get("print") == "1"})


# ---------- Loyalty cards ----------


class CardForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LoyaltyCard
        fields = ["name", "phone", "stamps", "is_active"]


@module_required("outlets")
def cards(request):
    q = request.GET.get("q", "").strip()
    qs = LoyaltyCard.objects.all()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(number=q))
    if request.method == "POST":
        try:
            card = loyalty.create_card(name=request.POST.get("name", ""), phone=request.POST.get("phone", ""))
            messages.success(request, _("New loyalty card %(n)s for %(name)s.") % {"n": card.number, "name": card.name})
            return redirect("outlets:cards")
        except BusinessError as e:
            messages.error(request, str(e))
    page = Paginator(qs.order_by("-last_visit", "name"), 50).get_page(request.GET.get("page"))
    return render(request, "outlets/cards.html", {"page_obj": page, "q": q, "needed": HotelSettings.load().loyalty_stamps})


@module_required("outlets")
def card(request, pk):
    c = get_object_or_404(LoyaltyCard, pk=pk)
    form = CardForm(request.POST or None, instance=c)
    if request.method == "POST":
        if not request.user.is_manager:
            messages.error(request, _("Only a manager can change a loyalty card."))
        elif form.is_valid():
            form.save()
            from apps.core.models import audit

            audit(request.user, "loyalty.edit", str(c), c)
            messages.success(request, _("Saved."))
            return redirect("outlets:card", pk=c.pk)
    visits = c.orders.exclude(status="open").select_related("outlet").order_by("-closed_at")[:30]
    return render(request, "outlets/card.html", {"c": c, "form": form, "visits": visits, "needed": HotelSettings.load().loyalty_stamps})


