from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, F, Q, Sum
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.permissions import module_required
from apps.core.crud import CrudCreateView, CrudListView, CrudUpdateView
from apps.core.exceptions import BusinessError
from apps.core.forms import DateInput, StyledFormMixin
from apps.finance.models import Charge, Payment
from apps.finance.views import _range
from apps.outlets.models import Item, Outlet

from . import services
from .models import ZERO, Delivery, RecipeLine, StockCount, StockItem, StockMove, Supplier

TABS = [
    ("inventory:stock", _("Stock")),
    ("inventory:delivery_list", _("Deliveries")),
    ("inventory:recipes", _("Recipes")),
    ("inventory:count_list", _("Counts")),
    ("inventory:usage", _("Usage report")),
    ("inventory:supplier_list", _("Suppliers")),
]


# Outlets that sell physical goods (where "track 1:1 as stock" makes sense).
TRACKABLE_KINDS = {"restaurant", "bar", "cafe", "room_service", "minibar", "pool"}


def _qty(value) -> Decimal | None:
    value = (value or "").strip().replace(",", ".")
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        raise BusinessError(_("“%(v)s” is not a number.") % {"v": value})


# ---------- Stock overview ----------


@module_required("inventory")
def stock(request):
    qs = StockItem.objects.select_related("supplier").filter(is_active=True)
    group = request.GET.get("group", "")
    if group:
        qs = qs.filter(group=group)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(supplier__name__icontains=q))
    low_only = request.GET.get("low") == "1"
    items = list(qs)
    if low_only:
        items = [i for i in items if i.is_low]
    all_active = StockItem.objects.filter(is_active=True)
    return render(
        request,
        "inventory/stock.html",
        {
            "items": items,
            "groups": StockItem.Group.choices,
            "group": group,
            "q": q,
            "low_only": low_only,
            "total_value": sum((i.value for i in all_active), ZERO),
            "low_count": sum(1 for i in all_active if i.is_low),
            "item_count": all_active.count(),
            "tabs": TABS,
            "tab": "inventory:stock",
        },
    )


class WasteForm(StyledFormMixin, forms.Form):
    quantity = forms.DecimalField(label=_("Quantity"), min_value=Decimal("0.001"), decimal_places=3)
    reason = forms.CharField(label=_("What happened"), max_length=200)


@module_required("inventory")
def item_detail(request, pk):
    item = get_object_or_404(StockItem.objects.select_related("supplier"), pk=pk)
    waste_form = WasteForm(request.POST or None)
    if request.method == "POST" and waste_form.is_valid():
        try:
            services.record_waste(
                item, waste_form.cleaned_data["quantity"], user=request.user, reason=waste_form.cleaned_data["reason"]
            )
            messages.success(request, _("Waste recorded."))
            return redirect("inventory:item_detail", pk=item.pk)
        except BusinessError as e:
            messages.error(request, str(e))
    moves = Paginator(item.moves.select_related("created_by", "order", "delivery"), 30).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "inventory/item_detail.html",
        {
            "item": item,
            "moves": moves,
            "page_obj": moves,
            "waste_form": waste_form,
            "used_in": item.used_in.select_related("item__category__outlet"),
            "tabs": TABS,
            "tab": "inventory:stock",
        },
    )


class StockItemForm(StyledFormMixin, forms.ModelForm):
    opening = forms.DecimalField(
        label=_("In stock now"),
        required=False,
        min_value=0,
        decimal_places=3,
        help_text=_("How much you have today. Later changes come from deliveries, sales and counts."),
    )

    class Meta:
        model = StockItem
        fields = ["name", "group", "unit", "min_level", "cost", "supplier", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)
        if self.instance.pk:
            del self.fields["opening"]


class StockItemCreate(CrudCreateView):
    module = "inventory"
    model = StockItem
    form_class = StockItemForm
    title = _("Stock")
    singular = _("stock item")
    list_url_name = "inventory:stock"

    def form_valid(self, form):
        response = super().form_valid(form)
        opening = form.cleaned_data.get("opening")
        if opening:
            services._move(self.object, StockMove.Kind.ADJUST, opening, user=self.request.user, note=_("Opening stock"))
        return response


class StockItemEdit(CrudUpdateView):
    module = "inventory"
    model = StockItem
    form_class = StockItemForm
    title = _("Stock")
    singular = _("stock item")
    list_url_name = "inventory:stock"

    def get_success_url(self):
        return reverse("inventory:item_detail", args=[self.object.pk])


# ---------- Deliveries ----------


@module_required("inventory")
def delivery_list(request):
    start, end = _range(request)
    qs = Delivery.objects.filter(business_date__range=(start, end)).select_related("supplier", "created_by")
    qs = qs.annotate(lines=Count("moves"))
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "inventory/deliveries.html",
        {
            "page_obj": page,
            "start": start,
            "end": end,
            "total": qs.aggregate(t=Sum("total"))["t"] or ZERO,
            "tabs": TABS,
            "tab": "inventory:delivery_list",
        },
    )


class DeliveryHeaderForm(StyledFormMixin, forms.Form):
    supplier = forms.ModelChoiceField(label=_("Supplier"), queryset=Supplier.objects.none(), required=False)
    business_date = forms.DateField(label=_("Date"), widget=DateInput, initial=timezone.localdate)
    reference = forms.CharField(label=_("Invoice / reference"), max_length=80, required=False)
    note = forms.CharField(label=_("Note"), max_length=255, required=False)
    record_expense = forms.BooleanField(
        label=_("Also record as an expense"),
        required=False,
        initial=True,
        help_text=_("Adds the total to Finance → Expenses (Food & drink stock)."),
    )
    paid_with = forms.ChoiceField(label=_("Paid with"), choices=Payment.Method.choices, initial=Payment.Method.CASH)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)


@module_required("inventory")
def delivery_create(request):
    form = DeliveryHeaderForm(request.POST or None)
    items = StockItem.objects.filter(is_active=True)
    rows = []
    if request.method == "POST":
        ids = request.POST.getlist("item")
        qtys = request.POST.getlist("qty")
        costs = request.POST.getlist("cost")
        try:
            lines = []
            by_id = {str(i.pk): i for i in items}
            for i, q, c in zip(ids, qtys, costs):
                rows.append({"item": i, "qty": q, "cost": c})
                if not i:
                    continue
                if i not in by_id:
                    raise BusinessError(_("Choose an item from the list."))
                qty = _qty(q)
                if qty is None:
                    continue
                lines.append(services.DeliveryLine(by_id[i], qty, _qty(c) or ZERO))
            if form.is_valid():
                d = form.cleaned_data
                delivery = services.receive_delivery(
                    lines,
                    user=request.user,
                    supplier=d["supplier"],
                    business_date=d["business_date"],
                    reference=d["reference"],
                    note=d["note"],
                    record_expense=d["record_expense"],
                    paid_with=d["paid_with"],
                )
                messages.success(request, _("Delivery saved. Stock updated."))
                return redirect("inventory:delivery_detail", pk=delivery.pk)
        except BusinessError as e:
            messages.error(request, str(e))
    preselect = request.GET.get("item", "")
    if not rows:
        rows = [{"item": preselect, "qty": "", "cost": ""}] + [{"item": "", "qty": "", "cost": ""} for _i in range(4)]
    return render(
        request,
        "inventory/delivery_form.html",
        {"form": form, "items": items, "rows": rows, "tabs": TABS, "tab": "inventory:delivery_list"},
    )


@module_required("inventory")
def delivery_detail(request, pk):
    delivery = get_object_or_404(Delivery.objects.select_related("supplier", "expense", "created_by"), pk=pk)
    return render(
        request,
        "inventory/delivery_detail.html",
        {
            "d": delivery,
            "moves": delivery.moves.select_related("stock_item"),
            "tabs": TABS,
            "tab": "inventory:delivery_list",
        },
    )


# ---------- Counts ----------


@module_required("inventory")
def count_list(request):
    page = Paginator(StockCount.objects.select_related("created_by").annotate(lines=Count("moves")), 50).get_page(
        request.GET.get("page")
    )
    return render(request, "inventory/counts.html", {"page_obj": page, "tabs": TABS, "tab": "inventory:count_list"})


@module_required("inventory")
def count_create(request):
    group = request.GET.get("group", "")
    items = StockItem.objects.filter(is_active=True)
    if group:
        items = items.filter(group=group)
    if request.method == "POST":
        try:
            counted = {}
            for item in items:
                value = _qty(request.POST.get(f"c{item.pk}"))
                if value is not None:
                    counted[item.pk] = value
            count = services.apply_count(counted, user=request.user, note=request.POST.get("note", "")[:255])
            messages.success(request, _("Stock count saved."))
            return redirect("inventory:count_detail", pk=count.pk)
        except BusinessError as e:
            messages.error(request, str(e))
    grouped: dict[str, list] = {}
    labels = dict(StockItem.Group.choices)
    for item in items:
        grouped.setdefault(labels[item.group], []).append(item)
    return render(
        request,
        "inventory/count_form.html",
        {
            "grouped": grouped,
            "groups": StockItem.Group.choices,
            "group": group,
            "posted": {i.pk: request.POST.get(f"c{i.pk}", "") for i in items} if request.method == "POST" else {},
            "tabs": TABS,
            "tab": "inventory:count_list",
        },
    )


@module_required("inventory")
def count_detail(request, pk):
    count = get_object_or_404(StockCount.objects.select_related("created_by"), pk=pk)
    moves = count.moves.select_related("stock_item").annotate(before=F("balance") - F("quantity"))
    return render(
        request,
        "inventory/count_detail.html",
        {"c": count, "moves": moves, "tabs": TABS, "tab": "inventory:count_list"},
    )


# ---------- Recipes ----------


@module_required("inventory")
def recipes(request):
    outlet_id = request.GET.get("outlet", "")
    items = Item.objects.select_related("category__outlet").prefetch_related("recipe__stock_item")
    if outlet_id:
        items = items.filter(category__outlet_id=outlet_id)
    q = request.GET.get("q", "").strip()
    if q:
        items = items.filter(name__icontains=q)
    rows = []
    for item in items.filter(is_active=True):
        lines = list(item.recipe.all())
        cost = sum((r.quantity * r.stock_item.cost for r in lines), ZERO).quantize(Decimal("0.01"))
        rows.append(
            {
                "item": item,
                "lines": lines,
                "cost": cost,
                "margin": (100 - cost * 100 / item.price).quantize(Decimal("1")) if lines and item.price else None,
                "can_track": not lines
                and item.duration_minutes is None
                and item.category.outlet.kind in TRACKABLE_KINDS,
            }
        )
    return render(
        request,
        "inventory/recipes.html",
        {
            "rows": rows,
            "outlets": Outlet.objects.filter(is_active=True),
            "outlet_id": outlet_id,
            "q": q,
            "without": sum(1 for r in rows if not r["lines"]),
            "tabs": TABS,
            "tab": "inventory:recipes",
        },
    )


@module_required("inventory")
def recipe_edit(request, item_id):
    item = get_object_or_404(Item.objects.select_related("category__outlet"), pk=item_id)
    stock_items = StockItem.objects.filter(is_active=True)
    if request.method == "POST":
        by_id = {str(s.pk): s for s in stock_items}
        try:
            wanted: dict[int, Decimal] = {}
            for sid, q in zip(request.POST.getlist("stock"), request.POST.getlist("qty")):
                qty = _qty(q)
                if not sid or qty is None:
                    continue
                if sid not in by_id or qty <= 0:
                    raise BusinessError(_("Each line needs a stock item and a quantity above 0."))
                wanted[int(sid)] = wanted.get(int(sid), ZERO) + qty
            item.recipe.exclude(stock_item_id__in=wanted).delete()
            for sid, qty in wanted.items():
                RecipeLine.objects.update_or_create(item=item, stock_item_id=sid, defaults={"quantity": qty})
            messages.success(request, _("Recipe for %(item)s saved.") % {"item": item.name})
            return redirect(f"{reverse('inventory:recipes')}?outlet={item.category.outlet_id}")
        except BusinessError as e:
            messages.error(request, str(e))
    lines = [{"stock": r.stock_item_id, "qty": f"{r.quantity.normalize():f}"} for r in item.recipe.all()]
    lines += [{"stock": "", "qty": ""} for _i in range(max(2, 5 - len(lines)))]
    return render(
        request,
        "inventory/recipe_form.html",
        {
            "item": item,
            "lines": lines,
            "stock_items": stock_items,
            "cost": services.recipe_cost(item),
            "tabs": TABS,
            "tab": "inventory:recipes",
        },
    )


@module_required("inventory")
def recipe_track(request, item_id):
    """One click for bottled drinks and similar: a stock item with the same name, used 1 per sale."""
    item = get_object_or_404(Item, pk=item_id)
    if request.method == "POST":
        stock_item, created = StockItem.objects.get_or_create(
            name=item.name, defaults={"group": StockItem.Group.DRINKS, "unit": StockItem.Unit.PIECE}
        )
        RecipeLine.objects.update_or_create(item=item, stock_item=stock_item, defaults={"quantity": 1})
        messages.success(
            request,
            _("%(item)s is now tracked as a stock item. Record a delivery or count to set how many you have.")
            % {"item": item.name},
        )
    return redirect(request.POST.get("next") or "inventory:recipes")


# ---------- Usage report ----------


@module_required("inventory")
def usage(request):
    start, end = _range(request)
    rows = services.usage(start, end)
    used_value = sum((r["used_value"] for r in rows), ZERO)
    wasted_value = sum((r["wasted_value"] for r in rows), ZERO)
    counted_value = sum((r["counted_value"] for r in rows), ZERO)
    sales = (
        Charge.objects.active()
        .filter(kind=Charge.Kind.OUTLET, business_date__range=(start, end))
        .aggregate(t=Sum("amount"))["t"]
        or ZERO
    )
    return render(
        request,
        "inventory/usage.html",
        {
            "rows": rows,
            "start": start,
            "end": end,
            "used_value": used_value,
            "wasted_value": wasted_value,
            "counted_value": counted_value,
            "sales": sales,
            "cost_pct": (used_value * 100 / sales).quantize(Decimal("0.1")) if sales else None,
            "tabs": TABS,
            "tab": "inventory:usage",
        },
    )


# ---------- Suppliers ----------


class SupplierList(CrudListView):
    module = "inventory"
    model = Supplier
    queryset = Supplier.objects.annotate(n=Count("items"))
    title = _("Stock")
    singular = _("supplier")
    tabs = TABS
    list_url_name = "inventory:supplier_list"
    create_url_name = "inventory:supplier_create"
    update_url_name = "inventory:supplier_edit"
    search_fields = ["name", "contact", "phone"]
    columns = [
        ("name", _("Name"), "text"),
        ("contact", _("Contact person"), "text"),
        ("phone", _("Phone"), "text"),
        ("n", _("Items"), "text"),
        ("is_active", _("Active"), "bool"),
    ]


class SupplierFormConfig:
    module = "inventory"
    model = Supplier
    title = _("Stock")
    singular = _("supplier")
    list_url_name = "inventory:supplier_list"

    def get_form_class(self):
        base = type("SupplierForm", (StyledFormMixin, forms.ModelForm), {})
        return modelform_factory(
            Supplier, form=base, fields=["name", "contact", "phone", "email", "tax_id", "notes", "is_active"]
        )


class SupplierCreate(SupplierFormConfig, CrudCreateView):
    pass


class SupplierEdit(SupplierFormConfig, CrudUpdateView):
    pass


def low_stock_count() -> int:
    return sum(1 for i in StockItem.objects.filter(is_active=True, min_level__gt=0) if i.is_low)
