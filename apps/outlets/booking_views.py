"""Screens for table bookings, minimum spend and one-tap sales."""

from datetime import date, timedelta

from django import forms
from django.contrib import messages
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.businessday import business_date, day_range
from apps.core.exceptions import BusinessError
from apps.core.forms import DateInput, StyledFormMixin, TimeInput
from apps.core.templatetags.innkeeper import money
from apps.finance.models import Payment

from . import bookings, services
from .models import Item, Order, OrderLine, Table, TableBooking
from .views import _order_for, _outlet_for


class BookingForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TableBooking
        fields = ["date", "time", "party_size", "name", "phone", "table", "duration_minutes", "minimum_spend", "note"]
        widgets = {"date": DateInput(), "time": TimeInput()}

    def __init__(self, *args, outlet=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["table"].queryset = Table.objects.filter(outlet=outlet, is_active=True)
        from apps.core.businessday import _cutoff

        if _cutoff():
            self.fields["date"].help_text = _("The evening's date: a booking at 01:00 on Saturday night goes on Saturday.")
        self.fields["table"].label_from_instance = lambda t: f"{t.name} · {t.seats} {_('seats')}" + (f" · {t.zone}" if t.zone else "")


@module_required("outlets")
def booking_list(request, pk):
    outlet = _outlet_for(request, pk)
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = business_date()
    rows = (
        TableBooking.objects.filter(outlet=outlet, date=day)
        .select_related("table", "order")
        .order_by("time", "id")
    )
    counts = rows.exclude(status__in=[TableBooking.Status.CANCELLED, TableBooking.Status.NO_SHOW]).aggregate(
        n=Count("id"), people=Sum("party_size")
    )
    return render(
        request,
        "outlets/bookings.html",
        {
            "outlet": outlet,
            "day": day,
            "prev": day - timedelta(days=1),
            "next": day + timedelta(days=1),
            "rows": rows,
            "counts": counts,
            "free_tables": outlet.tables.filter(is_active=True),
        },
    )


@module_required("outlets")
def booking_form(request, pk, booking_id=None):
    outlet = _outlet_for(request, pk)
    booking = get_object_or_404(TableBooking, pk=booking_id, outlet=outlet) if booking_id else TableBooking(outlet=outlet)
    initial = {}
    if not booking_id:
        initial = {"date": request.GET.get("date") or business_date(), "time": "20:00"}
        if request.GET.get("table"):
            initial["table"] = request.GET["table"]
    form = BookingForm(request.POST or None, instance=booking, initial=initial, outlet=outlet)
    if request.method == "POST" and form.is_valid():
        try:
            obj = bookings.save_booking(form.save(commit=False), request.user)
        except BusinessError as e:
            form.add_error(None, str(e))
        else:
            if obj.table and obj.party_size > obj.table.seats:
                messages.warning(
                    request,
                    _("Table %(t)s has %(s)s seats for %(n)s people.") % {"t": obj.table.name, "s": obj.table.seats, "n": obj.party_size},
                )
            messages.success(request, _("Booked: %(b)s") % {"b": obj})
            return redirect(f"{_bookings_url(outlet)}?date={obj.date:%Y-%m-%d}")
    return render(request, "outlets/booking_form.html", {"outlet": outlet, "form": form, "object": booking if booking_id else None})


def _bookings_url(outlet):
    from django.urls import reverse

    return reverse("outlets:bookings", args=[outlet.pk])


@require_POST
@module_required("outlets")
def booking_action(request, pk, booking_id):
    outlet = _outlet_for(request, pk)
    booking = get_object_or_404(TableBooking, pk=booking_id, outlet=outlet)
    action = request.POST.get("action")
    try:
        if action == "seat":
            table = None
            if request.POST.get("table"):
                table = get_object_or_404(Table, pk=request.POST["table"], outlet=outlet)
            order = bookings.seat(booking, request.user, table=table)
            messages.success(request, _("%(name)s seated at table %(t)s.") % {"name": booking.name, "t": order.table.name})
            return redirect("outlets:order", pk=order.pk)
        if action == "cancel":
            bookings.set_status(booking, TableBooking.Status.CANCELLED, request.user)
        elif action == "no_show":
            bookings.set_status(booking, TableBooking.Status.NO_SHOW, request.user)
    except BusinessError as e:
        messages.error(request, str(e))
    return redirect(f"{_bookings_url(outlet)}?date={booking.date:%Y-%m-%d}")


@require_POST
@module_required("outlets")
def minimum_spend(request, pk):
    order = _order_for(request, pk)
    try:
        line = bookings.top_up_minimum_spend(order, request.user)
        messages.success(request, _("%(amount)s added to reach the minimum spend.") % {"amount": money(line.unit_price)})
    except BusinessError as e:
        messages.error(request, str(e))
    return redirect("outlets:order", pk=order.pk)


# ---------- One-tap sale (entrance, ticket desk, takeaway) ----------


def quick_sale_context(outlet) -> dict:
    since, until = day_range(business_date())
    sold = (
        OrderLine.objects.filter(
            order__outlet=outlet, order__status=Order.Status.CLOSED, order__closed_at__gte=since, order__closed_at__lt=until
        )
        .values("item_id")
        .annotate(n=Sum("quantity"))
    )
    counts = {r["item_id"]: r["n"] for r in sold}
    categories = outlet.categories.prefetch_related("items__option_groups").all()
    menu = []
    for c in categories:
        items = [i for i in c.items.all() if i.is_active]
        for i in items:
            i.sold_today = counts.get(i.pk, 0)
            i.has_options = bool(i.option_groups.all())
        if items:
            menu.append({"category": c, "items": items})
    return {"quick_menu": menu, "sold_total": sum(counts.values())}


@require_POST
@module_required("outlets")
def quick_sell(request, pk):
    outlet = _outlet_for(request, pk)
    item = get_object_or_404(Item, pk=request.POST.get("item"), category__outlet=outlet)
    method = request.POST.get("method", Payment.Method.CASH)
    if method not in (Payment.Method.CASH, Payment.Method.CARD):
        method = Payment.Method.CASH
    try:
        qty = max(1, min(int(request.POST.get("quantity", "1") or 1), 50))
    except ValueError:
        qty = 1
    if item.option_groups.exists():  # needs choices: sell it through the normal order screen
        order = services.open_order(outlet, user=request.user, label=item.name)
        return redirect("outlets:order", pk=order.pk)
    try:
        order = services.open_order(outlet, user=request.user, label=item.name)
        services.add_item(order, item, user=request.user, quantity=qty)
        services.pay_order(order, method=method, user=request.user)
    except BusinessError as e:
        messages.error(request, str(e))
        return redirect("outlets:floor", pk=outlet.pk)
    order.refresh_from_db()
    messages.success(request, _("Sold: %(n)s × %(item)s · %(total)s") % {"n": qty, "item": item.name, "total": money(order.total)})
    from .views import _print_receipt, _receipt_printer

    printer = _receipt_printer(order)
    if printer and outlet.auto_print_receipt:
        _print_receipt(request, order, printer, cash=method == Payment.Method.CASH)
    from django.urls import reverse

    return redirect(f"{reverse('outlets:floor', args=[outlet.pk])}?method={method}")
