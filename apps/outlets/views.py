from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.crud import CrudCreateView, CrudListView, CrudUpdateView
from apps.core.exceptions import BusinessError
from apps.core.forms import StyledFormMixin
from apps.core.templatetags.innkeeper import money
from apps.finance.models import Payment
from apps.frontdesk.models import Reservation

from . import services
from .floorplan import floor_plan, floor_plan_save  # noqa: F401  (routed in urls.py)
from .models import Category, Item, KitchenTicket, Order, OrderLine, Outlet, Printer, PrintJob, Station, Table


def _outlet_for(request, pk) -> Outlet:
    outlet = get_object_or_404(Outlet, pk=pk, is_active=True)
    if not outlet.user_can_use(request.user):
        raise PermissionDenied
    return outlet


def _order_for(request, pk) -> Order:
    order = get_object_or_404(Order.objects.select_related("outlet", "table"), pk=pk)
    if not order.outlet.user_can_use(request.user):
        raise PermissionDenied
    return order


@module_required("outlets")
def home(request):
    outlets = [
        o
        for o in Outlet.objects.filter(is_active=True).annotate(
            open_count=Count("orders", filter=Q(orders__status=Order.Status.OPEN))
        )
        if o.user_can_use(request.user)
    ]
    if len(outlets) == 1:
        return redirect("outlets:floor", pk=outlets[0].pk)
    return render(request, "outlets/home.html", {"outlets": outlets})


@module_required("outlets")
def floor(request, pk):
    outlet = _outlet_for(request, pk)
    open_orders = (
        outlet.orders.filter(status=Order.Status.OPEN).select_related("table", "opened_by").prefetch_related("lines")
    )
    by_table = {o.table_id: o for o in open_orders if o.table_id}
    ready_orders = set(
        KitchenTicket.objects.filter(order__in=open_orders, status=KitchenTicket.Status.READY).values_list(
            "order_id", flat=True
        )
    )
    unsent_orders = set(
        OrderLine.objects.filter(order__in=open_orders, status=OrderLine.Status.NEW, quantity__gt=0).values_list(
            "order_id", flat=True
        )
    )
    for o in open_orders:
        o.has_ready, o.has_unsent = o.pk in ready_orders, o.pk in unsent_orders
    all_tables = list(outlet.tables.filter(is_active=True))
    zones = []
    for t in all_tables:
        if t.zone not in zones:
            zones.append(t.zone)
    zone = request.GET.get("zone", zones[0] if zones else "")
    if zone not in zones and zones:
        zone = zones[0]
    tables = [
        {
            "table": t,
            "order": by_table.get(t.pk),
            "left": t.pos_x / 10,
            "top": t.pos_y / 6.4,
            "width": t.width / 10,
            "height": t.height / 6.4,
        }
        for t in all_tables
        if t.zone == zone
    ]
    open_orders = list(open_orders)
    loose_orders = [o for o in open_orders if not o.table_id]
    return render(
        request,
        "outlets/floor.html",
        {
            "outlet": outlet,
            "tables": tables,
            "loose_orders": loose_orders,
            "zones": zones,
            "zone": zone,
            "busy_counts": {z: sum(1 for t in all_tables if t.zone == z and t.pk in by_table) for z in zones},
        },
    )


@module_required("outlets")
def open_table(request, pk, table_id):
    outlet = _outlet_for(request, pk)
    table = get_object_or_404(Table, pk=table_id, outlet=outlet, is_active=True)
    try:
        order = services.open_order(outlet, table=table, user=request.user)
    except BusinessError as e:
        messages.error(request, str(e))
        return redirect("outlets:floor", pk=pk)
    return redirect("outlets:order", pk=order.pk)


@require_POST
@module_required("outlets")
def new_order(request, pk):
    outlet = _outlet_for(request, pk)
    try:
        order = services.open_order(outlet, user=request.user, label=request.POST.get("label", "").strip()[:80])
    except BusinessError as e:
        messages.error(request, str(e))
        return redirect("outlets:floor", pk=pk)
    return redirect("outlets:order", pk=order.pk)


@module_required("outlets")
def order_view(request, pk):
    order = _order_for(request, pk)
    if not order.is_open:
        return redirect("outlets:receipt", pk=order.pk)
    categories = order.outlet.categories.prefetch_related("items").all()
    menu = [{"category": c, "items": [i for i in c.items.all() if i.is_active]} for c in categories]
    in_house = (
        Reservation.objects.filter(status=Reservation.Status.CHECKED_IN)
        .select_related("guest", "room")
        .order_by("room__number")
    )
    return render(
        request,
        "outlets/order.html",
        {
            "order": order,
            "outlet": order.outlet,
            "lines": order.active_lines.select_related("ticket").order_by("added_at", "id"),
            "removed_lines": order.lines.filter(quantity=0),
            "unsent": order.unsent_count,
            "ready_count": order.tickets.filter(status=KitchenTicket.Status.READY).count(),
            "menu": [m for m in menu if m["items"]],
            "in_house": in_house,
            "methods": Payment.Method.choices,
            "payments": order.payments.filter(voided=False).select_related("created_by"),
            "move_tables": order.outlet.tables.filter(is_active=True).exclude(pk=order.table_id),
            "item_count": sum(line.quantity for line in order.active_lines),
        },
    )


def _back_to_order(order):
    return redirect("outlets:order", pk=order.pk)


@require_POST
@module_required("outlets")
def add_item(request, pk):
    order = _order_for(request, pk)
    item = get_object_or_404(Item.objects.select_related("category"), pk=request.POST.get("item"))
    try:
        services.add_item(order, item, user=request.user, note=request.POST.get("note", "").strip()[:120])
    except BusinessError as e:
        messages.error(request, str(e))
    return _back_to_order(order)


@require_POST
@module_required("outlets")
def change_line(request, pk, line_id):
    order = _order_for(request, pk)
    line = get_object_or_404(OrderLine, pk=line_id, order=order)
    try:
        delta = int(request.POST.get("delta", "0"))
        services.change_quantity(line, delta, user=request.user)
    except (BusinessError, ValueError) as e:
        messages.error(request, str(e))
    return _back_to_order(order)


@require_POST
@module_required("outlets")
def update_order(request, pk):
    order = _order_for(request, pk)
    if order.is_open:
        try:
            order.guests = max(1, int(request.POST.get("guests", order.guests)))
        except ValueError:
            pass
        order.note = request.POST.get("note", order.note)[:255]
        order.save(update_fields=["guests", "note"])
    return _back_to_order(order)


def _decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ".").strip()) if str(value).strip() else None
    except (InvalidOperation, ValueError):
        raise BusinessError(_("Enter a valid amount."))


@require_POST
@module_required("outlets")
def settle(request, pk):
    order = _order_for(request, pk)
    how = request.POST.get("how")
    try:
        if how == "room":
            reservation = get_object_or_404(Reservation, pk=request.POST.get("reservation"))
            services.charge_to_room(order, reservation, user=request.user)
            messages.success(request, _("Charged to room %(room)s.") % {"room": reservation.room.number})
        elif how in Payment.Method.values:
            payment = services.pay_order(
                order,
                method=how,
                user=request.user,
                amount=_decimal(request.POST.get("amount", "")),
                tendered=_decimal(request.POST.get("tendered", "")),
                reference=request.POST.get("reference", "")[:80],
            )
            order.refresh_from_db()
            cash = how == Payment.Method.CASH
            if order.is_open:
                if cash:
                    _kick_drawer(order, request.user)
                messages.success(
                    request,
                    _("%(amount)s received. %(left)s left to pay.")
                    % {"amount": money(payment.amount), "left": money(order.remaining)},
                )
                return _back_to_order(order)
            if payment.change:
                messages.success(request, _("Paid. Give back %(change)s change.") % {"change": money(payment.change)})
            else:
                messages.success(request, _("Paid. The table is free again."))
        else:
            raise BusinessError(_("Choose how the bill is settled."))
    except BusinessError as e:
        messages.error(request, str(e))
        return _back_to_order(order)
    printer = _receipt_printer(order)
    wants_print = request.POST.get("print") == "1" or (printer and order.outlet.auto_print_receipt)
    if printer:
        if wants_print:
            _print_receipt(request, order, printer, cash=how == Payment.Method.CASH)
        elif how == Payment.Method.CASH:
            _kick_drawer(order, request.user)
        return redirect("outlets:floor", pk=order.outlet_id)
    url = reverse("outlets:receipt", args=[order.pk])
    return redirect(url + ("?print=1" if wants_print else ""))


# ---------- Printing ----------


def _receipt_printer(order):
    p = order.outlet.receipt_printer
    return p if p is not None and p.is_active else None


def _print_receipt(request, order, printer, *, cash=False) -> bool:
    from . import printing

    job = printing.submit(
        printer,
        f"{order.outlet}: {order.receipt_number or order.number}",
        printing.receipt_document(order, printer, open_drawer=cash),
        request.user,
    )
    if job.status == job.Status.DONE:
        messages.success(request, _("Sent to %(printer)s.") % {"printer": printer.name})
        return True
    messages.error(
        request,
        _("%(printer)s did not print: %(error)s You can retry under Outlets & menus → Printers.")
        % {"printer": printer.name, "error": job.error},
    )
    return False


def _kick_drawer(order, user) -> None:
    from . import printing

    printer = _receipt_printer(order)
    if printer and printer.open_drawer:
        printing.submit(printer, _("Open cash drawer"), printing.drawer_document(), user)


@require_POST
@module_required("outlets")
def print_bill(request, pk):
    """Print the bill on the outlet's printer, or open the browser print page if it has none."""
    order = _order_for(request, pk)
    printer = _receipt_printer(order)
    if not printer:
        return redirect(reverse("outlets:receipt", args=[order.pk]) + "?print=1")
    _print_receipt(request, order, printer)
    if order.is_open:
        return _back_to_order(order)
    return redirect(request.POST.get("next") or reverse("outlets:receipt", args=[order.pk]))


@require_POST
@module_required("outlets")
def send_order(request, pk):
    order = _order_for(request, pk)
    try:
        tickets = services.send_to_kitchen(order, user=request.user)
    except BusinessError as e:
        messages.error(request, str(e))
        return _back_to_order(order)
    if tickets:
        messages.success(request, _("Sent to %(stations)s.") % {"stations": ", ".join(t.station.name for t in tickets)})
    if request.POST.get("then") == "floor":
        return redirect("outlets:floor", pk=order.outlet_id)
    return _back_to_order(order)


@require_POST
@module_required("outlets")
def discount(request, pk):
    order = _order_for(request, pk)
    try:
        value = _decimal(request.POST.get("value", "")) or Decimal("0")
        kind = request.POST.get("kind", "percent")
        services.set_discount(
            order,
            user=request.user,
            percent=value if kind == "percent" else None,
            amount=value if kind == "amount" else None,
            reason=request.POST.get("reason", ""),
        )
    except BusinessError as e:
        messages.error(request, str(e))
    return _back_to_order(order)


@require_POST
@module_required("outlets")
def move(request, pk):
    order = _order_for(request, pk)
    table = get_object_or_404(Table, pk=request.POST.get("table"), outlet=order.outlet, is_active=True)
    try:
        target = services.move_order(order, table, user=request.user)
        messages.success(request, _("Moved to table %(name)s.") % {"name": table.name})
    except BusinessError as e:
        messages.error(request, str(e))
        return _back_to_order(order)
    return _back_to_order(target)


@require_POST
@module_required("outlets")
def void_payment(request, pk, payment_id):
    order = _order_for(request, pk)
    payment = get_object_or_404(Payment, pk=payment_id, order=order)
    try:
        services.void_payment(payment, user=request.user, reason=request.POST.get("reason", ""))
        messages.success(request, _("Entry voided."))
    except BusinessError as e:
        messages.error(request, str(e))
    return _back_to_order(order)


@require_POST
@module_required("outlets")
def void_receipt(request, pk):
    order = _order_for(request, pk)
    try:
        services.void_receipt(order, user=request.user, reason=request.POST.get("reason", ""))
        messages.success(request, _("Receipt voided."))
    except BusinessError as e:
        messages.error(request, str(e))
    return redirect("outlets:receipt", pk=order.pk)


@require_POST
@module_required("outlets")
def cancel(request, pk):
    order = _order_for(request, pk)
    try:
        services.cancel_order(order, user=request.user)
        messages.success(request, _("Order cancelled."))
    except BusinessError as e:
        messages.error(request, str(e))
        return _back_to_order(order)
    return redirect("outlets:floor", pk=order.outlet_id)


@module_required("outlets")
def receipt(request, pk):
    from apps.core.models import HotelSettings

    order = _order_for(request, pk)
    hs = HotelSettings.load()
    total = order.total
    vat = (total * hs.vat_fraction).quantize(Decimal("0.01"))
    room_charge = (
        order.charges.filter(folio__isnull=False, voided=False)
        .select_related("folio__reservation__room", "folio__reservation__guest")
        .first()
    )
    return render(
        request,
        "outlets/receipt.html",
        {
            "order": order,
            "lines": order.active_lines,
            "payments": order.payments.filter(voided=False),
            "room_charge": room_charge,
            "vat": vat,
            "net": total - vat,
            "auto_print": request.GET.get("print") == "1",
        },
    )


@module_required("outlets")
def receipts(request):
    """Every closed or voided bill, newest first, for reprinting or voiding."""
    qs = Order.objects.exclude(status=Order.Status.OPEN).select_related("outlet", "table", "closed_by", "opened_by")
    qs = qs.exclude(status=Order.Status.CANCELLED, receipt_number="")
    outlets = [o for o in Outlet.objects.all() if o.user_can_use(request.user)]
    qs = qs.filter(outlet__in=outlets)
    day = request.GET.get("date", "")
    if day:
        qs = qs.filter(closed_at__date=day)
    if request.GET.get("outlet"):
        qs = qs.filter(outlet_id=request.GET["outlet"])
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(receipt_number__icontains=q) | Q(label__icontains=q) | Q(table__name=q))
    page = Paginator(qs.order_by("-closed_at"), 50).get_page(request.GET.get("page"))
    return render(
        request,
        "outlets/receipts.html",
        {"page_obj": page, "object_list": page.object_list, "outlets": outlets, "q": q, "day": day},
    )


# ---------- Setup (managers) ----------

SETUP_TABS = [
    ("outlets:setup", _("Outlets")),
    ("outlets:category_list", _("Categories")),
    ("outlets:item_list", _("Menu & services")),
    ("outlets:table_list", _("Tables")),
    ("outlets:station_list", _("Stations")),
    ("outlets:printer_list", _("Printers")),
]


class OutletForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Outlet
        fields = [
            "name",
            "kind",
            "uses_tables",
            "receipt_printer",
            "auto_print_receipt",
            "menu_public",
            "menu_intro",
            "sort_order",
            "is_active",
            "staff",
        ]
        widgets = {"staff": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounts.models import Role, User

        self.fields["staff"].queryset = User.objects.filter(is_active=True, role=Role.OUTLET)


class OutletList(CrudListView):
    model = Outlet
    title = _("Outlets & menus")
    singular = _("outlet")
    tabs = SETUP_TABS
    list_url_name = "outlets:setup"
    create_url_name = "outlets:outlet_create"
    update_url_name = "outlets:outlet_edit"
    row_actions = [
        (_("Floor plan"), "outlets:floor_plan", "move", "uses_tables"),
        (_("Menu & QR"), "outlets:menu_admin", "qr", ""),
    ]
    columns = [
        ("name", _("Name"), "text"),
        ("kind", _("Type"), "choice"),
        ("uses_tables", _("Tables"), "bool"),
        ("is_active", _("Active"), "bool"),
    ]


class OutletFormConfig:
    model = Outlet
    form_class = OutletForm
    title = _("Outlets & menus")
    singular = _("outlet")
    list_url_name = "outlets:setup"


class OutletCreate(OutletFormConfig, CrudCreateView):
    pass


class OutletEdit(OutletFormConfig, CrudUpdateView):
    pass


class CategoryList(CrudListView):
    model = Category
    queryset = Category.objects.select_related("outlet")
    title = _("Outlets & menus")
    singular = _("category")
    tabs = SETUP_TABS
    list_url_name = "outlets:category_list"
    create_url_name = "outlets:category_create"
    update_url_name = "outlets:category_edit"
    search_fields = ["name", "outlet__name"]
    columns = [
        ("name", _("Name"), "text"),
        ("outlet.name", _("Outlet"), "text"),
        ("station.name", _("Prepared at"), "text"),
        ("sort_order", _("Order"), "text"),
    ]


class CategoryFormConfig:
    model = Category
    fields = ["outlet", "name", "name_en", "station", "sort_order"]
    title = _("Outlets & menus")
    singular = _("category")
    list_url_name = "outlets:category_list"

    def get_form_class(self):
        from django.forms import modelform_factory

        base = type("CategoryForm", (StyledFormMixin, forms.ModelForm), {})
        return modelform_factory(self.model, form=base, fields=self.fields)


class CategoryCreate(CategoryFormConfig, CrudCreateView):
    pass


class CategoryEdit(CategoryFormConfig, CrudUpdateView):
    pass


class ItemForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            "category",
            "name",
            "name_en",
            "price",
            "description",
            "description_en",
            "duration_minutes",
            "sort_order",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.select_related("outlet")


class ItemList(CrudListView):
    model = Item
    queryset = Item.objects.select_related("category", "category__outlet")
    title = _("Outlets & menus")
    singular = _("item")
    tabs = SETUP_TABS
    list_url_name = "outlets:item_list"
    create_url_name = "outlets:item_create"
    update_url_name = "outlets:item_edit"
    search_fields = ["name", "category__name", "category__outlet__name"]
    columns = [
        ("name", _("Name"), "text"),
        ("category.outlet.name", _("Outlet"), "text"),
        ("category.name", _("Category"), "text"),
        ("price", _("Price"), "money"),
        ("is_active", _("Available"), "bool"),
    ]


class ItemFormConfig:
    model = Item
    form_class = ItemForm
    title = _("Outlets & menus")
    singular = _("item")
    list_url_name = "outlets:item_list"


class ItemCreate(ItemFormConfig, CrudCreateView):
    pass


class ItemEdit(ItemFormConfig, CrudUpdateView):
    pass


class TableList(CrudListView):
    model = Table
    queryset = Table.objects.select_related("outlet")
    title = _("Outlets & menus")
    singular = _("table")
    tabs = SETUP_TABS
    list_url_name = "outlets:table_list"
    create_url_name = "outlets:table_create"
    update_url_name = "outlets:table_edit"
    columns = [
        ("name", _("Name"), "text"),
        ("outlet.name", _("Outlet"), "text"),
        ("seats", _("Seats"), "text"),
        ("is_active", _("Active"), "bool"),
    ]


class TableFormConfig:
    model = Table
    fields = ["outlet", "name", "seats", "zone", "shape", "sort_order", "is_active"]
    title = _("Outlets & menus")
    singular = _("table")
    list_url_name = "outlets:table_list"

    def get_form_class(self):
        from django.forms import modelform_factory

        base = type("TableForm", (StyledFormMixin, forms.ModelForm), {})
        return modelform_factory(self.model, form=base, fields=self.fields)


class TableCreate(TableFormConfig, CrudCreateView):
    pass


class TableEdit(TableFormConfig, CrudUpdateView):
    pass


# ---------- Stations & printers ----------


class StationList(CrudListView):
    model = Station
    queryset = Station.objects.select_related("printer")
    title = _("Outlets & menus")
    singular = _("station")
    tabs = SETUP_TABS
    list_url_name = "outlets:station_list"
    create_url_name = "outlets:station_create"
    update_url_name = "outlets:station_edit"
    row_actions = [(_("Open screen"), "outlets:board", "grid", "is_active")]
    columns = [
        ("name", _("Name"), "text"),
        ("printer.name", _("Ticket printer"), "text"),
        ("is_active", _("Active"), "bool"),
    ]


class StationFormConfig:
    model = Station
    fields = ["name", "printer", "sort_order", "is_active"]
    title = _("Outlets & menus")
    singular = _("station")
    list_url_name = "outlets:station_list"

    def get_form_class(self):
        from django.forms import modelform_factory

        base = type("StationForm", (StyledFormMixin, forms.ModelForm), {})
        return modelform_factory(self.model, form=base, fields=self.fields)


class StationCreate(StationFormConfig, CrudCreateView):
    pass


class StationEdit(StationFormConfig, CrudUpdateView):
    pass


class PrinterForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Printer
        fields = ["name", "connection", "address", "port", "system_name", "paper_width", "open_drawer", "is_active"]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("connection") == Printer.Connection.NETWORK and not cleaned.get("address"):
            self.add_error("address", _("Enter the printer's IP address."))
        if cleaned.get("connection") == Printer.Connection.SYSTEM and not cleaned.get("system_name"):
            self.add_error("system_name", _("Enter the printer's name exactly as Windows shows it."))
        return cleaned


@module_required("management")
def printer_list(request):
    from django.db.models import Count, Q

    printers = Printer.objects.annotate(failed=Count("jobs", filter=Q(jobs__status=PrintJob.Status.FAILED)))
    jobs = PrintJob.objects.select_related("printer", "created_by")[:30]
    return render(
        request,
        "outlets/printers.html",
        {
            "printers": printers,
            "jobs": jobs,
            "tabs": [(reverse(n), label, n == "outlets:printer_list") for n, label in SETUP_TABS],
        },
    )


class PrinterFormConfig:
    model = Printer
    form_class = PrinterForm
    title = _("Outlets & menus")
    singular = _("printer")
    list_url_name = "outlets:printer_list"
    template_name = "outlets/printer_form.html"


class PrinterCreate(PrinterFormConfig, CrudCreateView):
    pass


class PrinterEdit(PrinterFormConfig, CrudUpdateView):
    pass


@require_POST
@module_required("management")
def printer_test(request, pk):
    from . import printing

    printer = get_object_or_404(Printer, pk=pk)
    job = printing.submit(printer, _("Test print"), printing.test_document(printer), request.user)
    if job.status == PrintJob.Status.DONE:
        messages.success(request, _("Test page sent to %(printer)s.") % {"printer": printer.name})
    else:
        messages.error(request, job.error)
    return redirect(request.POST.get("next") or "outlets:printer_list")


@require_POST
@module_required("outlets")
def job_retry(request, pk):
    from . import printing

    job = get_object_or_404(PrintJob, pk=pk)
    printing.run_job(job)
    if job.status == PrintJob.Status.DONE:
        messages.success(request, _("Printed."))
    else:
        messages.error(request, job.error)
    return redirect("outlets:printer_list")
