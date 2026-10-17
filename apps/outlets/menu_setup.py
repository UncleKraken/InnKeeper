"""Menu extras managed in Outlets & menus: item options (sizes, extras…) and time-based prices."""

from django import forms
from django.contrib import messages
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from apps.core.crud import CrudCreateView, CrudListView, CrudUpdateView
from apps.core.forms import StyledFormMixin, TimeInput
from apps.core.models import audit

from .models import Category, Item, Option, OptionGroup, Outlet, PriceRule


class _ItemChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.category.outlet.name} · {obj.name}"


class _CategoryChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.outlet.name} · {obj.name}"


class OptionGroupForm(StyledFormMixin, forms.ModelForm):
    items = _ItemChoice(
        queryset=Item.objects.none(),
        required=False,
        label=_("Offered with these items"),
        widget=forms.CheckboxSelectMultiple(attrs={"data-full": "1"}),
    )

    class Meta:
        model = OptionGroup
        fields = ["name", "name_en", "required", "multiple", "sort_order", "items"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["items"].queryset = Item.objects.select_related("category__outlet").order_by(
            "category__outlet__name", "category__sort_order", "sort_order", "name"
        )


class OptionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Option
        fields = ["name", "name_en", "price_change", "is_active"]


OptionFormSet = inlineformset_factory(OptionGroup, Option, form=OptionForm, extra=3, can_delete=True)


class OptionGroupList(CrudListView):
    model = OptionGroup
    title = _("Outlets & menus")
    singular = _("option group")
    list_url_name = "outlets:option_list"
    create_url_name = "outlets:option_create"
    update_url_name = "outlets:option_edit"
    search_fields = ["name"]
    columns = [
        ("name", _("Name"), "text"),
        ("choices", _("Choices"), "text"),
        ("item_count", _("Items"), "text"),
        ("required", _("Must choose"), "bool"),
        ("multiple", _("Several allowed"), "bool"),
    ]

    def get_queryset(self):
        groups = list(super().get_queryset().prefetch_related("options", "items"))
        for g in groups:
            g.choices = ", ".join(o.name for o in g.options.all())
            g.item_count = len(g.items.all())
        return groups

    @property
    def tabs(self):
        from .views import SETUP_TABS

        return SETUP_TABS


class _OptionGroupFormMixin:
    model = OptionGroup
    form_class = OptionGroupForm
    title = _("Outlets & menus")
    singular = _("option group")
    list_url_name = "outlets:option_list"
    template_name = "outlets/option_group_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["formset"] = kwargs.get("formset") or OptionFormSet(instance=getattr(self, "object", None))
        return ctx

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() if hasattr(self, "pk_url_kwarg") and kwargs.get("pk") else None
        form = self.get_form()
        formset = OptionFormSet(request.POST, instance=self.object or OptionGroup())
        if form.is_valid() and formset.is_valid():
            self.object = form.save()
            formset.instance = self.object
            formset.save()
            audit(request.user, "option_group.save", str(self.object), self.object)
            messages.success(request, _("Saved %(obj)s.") % {"obj": self.object})
            from django.shortcuts import redirect

            return redirect(self.get_success_url())
        return self.render_to_response(self.get_context_data(form=form, formset=formset))


class OptionGroupCreate(_OptionGroupFormMixin, CrudCreateView):
    pass


class OptionGroupEdit(_OptionGroupFormMixin, CrudUpdateView):
    pass


# ---------- Time-based prices ----------


class PriceRuleForm(StyledFormMixin, forms.ModelForm):
    field_order = ["name", "percent", "start_time", "end_time", "weekdays", "outlets", "categories", "is_active"]
    weekdays = forms.MultipleChoiceField(
        label=_("Days"),
        choices=PriceRule.WEEKDAYS,
        widget=forms.CheckboxSelectMultiple(attrs={"data-full": "1"}),
        initial=[d for d, _l in PriceRule.WEEKDAYS],
    )
    outlets = forms.ModelMultipleChoiceField(
        queryset=Outlet.objects.filter(is_active=True),
        required=False,
        label=_("Outlets"),
        help_text=_("Empty: all outlets."),
        widget=forms.CheckboxSelectMultiple(attrs={"data-full": "1"}),
    )
    categories = _CategoryChoice(
        queryset=Category.objects.select_related("outlet").order_by("outlet__name", "sort_order"),
        required=False,
        label=_("Categories"),
        help_text=_("Empty: the whole menu."),
        widget=forms.CheckboxSelectMultiple(attrs={"data-full": "1"}),
    )

    class Meta:
        model = PriceRule
        fields = ["name", "percent", "start_time", "end_time", "is_active", "outlets", "categories"]
        widgets = {"start_time": TimeInput(), "end_time": TimeInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["weekdays"] = list(self.instance.days)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start_time") and cleaned.get("start_time") == cleaned.get("end_time"):
            self.add_error("end_time", _("“Until” must be different from “from”."))
        return cleaned

    def save(self, commit=True):
        self.instance.days = "".join(sorted(self.cleaned_data["weekdays"]))
        return super().save(commit)


class PriceRuleList(CrudListView):
    model = PriceRule
    title = _("Outlets & menus")
    singular = _("time-based price")
    list_url_name = "outlets:price_rule_list"
    create_url_name = "outlets:price_rule_create"
    update_url_name = "outlets:price_rule_edit"
    columns = [
        ("label", _("Name"), "text"),
        ("when", _("When"), "text"),
        ("is_active", _("Active"), "bool"),
    ]

    def get_queryset(self):
        rules = list(super().get_queryset())
        names = dict(PriceRule.WEEKDAYS)
        for r in rules:
            days = "" if r.days == "0123456" else " · " + ", ".join(str(names[d]) for d in r.days)
            r.when = f"{r.start_time:%H:%M}–{r.end_time:%H:%M}{days}"
        return rules

    @property
    def tabs(self):
        from .views import SETUP_TABS

        return SETUP_TABS


class _PriceRuleFormConfig:
    model = PriceRule
    form_class = PriceRuleForm
    title = _("Outlets & menus")
    singular = _("time-based price")
    list_url_name = "outlets:price_rule_list"


class PriceRuleCreate(_PriceRuleFormConfig, CrudCreateView):
    pass


class PriceRuleEdit(_PriceRuleFormConfig, CrudUpdateView):
    pass
