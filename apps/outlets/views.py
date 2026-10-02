from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.crud import CrudCreateView, CrudListView, CrudUpdateView
from apps.core.exceptions import BusinessError
from apps.core.forms import StyledFormMixin
from apps.finance.models import Payment
from apps.frontdesk.models import Reservation

from . import services
from .models import Category, Item, Order, OrderLine, Outlet, Table


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
    tables = [{"table": t, "order": by_table.get(t.pk)} for t in outlet.tables.filter(is_active=True)]
    loose_orders = [o for o in open_orders if not o.table_id]
    return render(request, "outlets/floor.html", {"outlet": outlet, "tables": tables, "loose_orders": loose_orders})


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
            "lines": order.lines.all(),
            "menu": [m for m in menu if m["items"]],
            "in_house": in_house,
            "methods": Payment.Method.choices,
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
            services.pay_order(order, method=how, user=request.user, reference=request.POST.get("reference", "")[:80])
            messages.success(request, _("Paid. The table is free again."))
        else:
            raise BusinessError(_("Choose how the bill is settled."))
    except BusinessError as e:
        messages.error(request, str(e))
        return _back_to_order(order)
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
    order = _order_for(request, pk)
    room_charge = (
        order.charges.filter(folio__isnull=False)
        .select_related("folio__reservation__room", "folio__reservation__guest")
        .first()
    )
    return render(
        request,
        "outlets/receipt.html",
        {"order": order, "lines": order.lines.all(), "payment": order.payments.first(), "room_charge": room_charge},
    )


# ---------- Setup (managers) ----------

SETUP_TABS = [
    ("outlets:setup", _("Outlets")),
    ("outlets:category_list", _("Categories")),
    ("outlets:item_list", _("Menu & services")),
    ("outlets:table_list", _("Tables")),
]


class OutletForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Outlet
        fields = ["name", "kind", "uses_tables", "sort_order", "is_active", "staff"]
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
    columns = [("name", _("Name"), "text"), ("outlet.name", _("Outlet"), "text"), ("sort_order", _("Order"), "text")]


class CategoryFormConfig:
    model = Category
    fields = ["outlet", "name", "sort_order"]
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
        fields = ["category", "name", "price", "description", "duration_minutes", "sort_order", "is_active"]

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
    fields = ["outlet", "name", "seats", "sort_order", "is_active"]
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
