from django import forms
from django.utils.translation import gettext_lazy


class StyledFormMixin:
    """Adds InnKeeper CSS classes to every widget so templates stay simple."""

    full_width_fields: tuple[str, ...] = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
                if isinstance(widget, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                    widget.attrs["data-full"] = "1"
                continue
            widget.attrs["class"] = (widget.attrs.get("class", "") + " input").strip()
            if isinstance(widget, forms.Textarea):
                widget.attrs["rows"] = 3
                widget.attrs["data-full"] = "1"
            if name in self.full_width_fields:
                widget.attrs["data-full"] = "1"


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%d")


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%H:%M")


class SetupForm(StyledFormMixin, forms.Form):
    MODULE_CHOICES = [
        ("rooms", gettext_lazy("Rooms & front desk")),
        ("housekeeping", gettext_lazy("Housekeeping")),
        ("maintenance", gettext_lazy("Maintenance")),
        ("outlets", gettext_lazy("Restaurant, bar & services")),
    ]

    business_type = forms.ChoiceField(widget=forms.RadioSelect)
    name = forms.CharField(label=gettext_lazy("Business name"), max_length=120)
    language = forms.ChoiceField(label=gettext_lazy("Main language"), choices=[("sq", "Shqip"), ("en", "English")])
    address = forms.CharField(label=gettext_lazy("Address"), max_length=255, required=False)
    tax_id = forms.CharField(label=gettext_lazy("Tax ID (NIPT)"), max_length=40, required=False)
    phone = forms.CharField(label=gettext_lazy("Phone"), max_length=40, required=False)
    email = forms.EmailField(label=gettext_lazy("Email"), required=False)
    currency = forms.ChoiceField(
        label=gettext_lazy("Currency"),
        choices=[
            ("EUR", "Euro (€)"),
            ("ALL", "Lek (L)"),
            ("USD", "US dollar ($)"),
            ("GBP", "Pound (£)"),
            ("CHF", "Franc (CHF)"),
        ],
    )
    vat_rate = forms.DecimalField(
        label=gettext_lazy("VAT rate (%)"), min_value=0, max_value=50, decimal_places=2, initial=20
    )
    modules = forms.MultipleChoiceField(
        label=gettext_lazy("What do you use?"),
        choices=MODULE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    floors = forms.IntegerField(label=gettext_lazy("Floors"), min_value=0, max_value=40, initial=2, required=False)
    rooms_per_floor = forms.IntegerField(
        label=gettext_lazy("Rooms per floor"), min_value=0, max_value=99, initial=6, required=False
    )
    room_rate = forms.DecimalField(
        label=gettext_lazy("Standard nightly rate"), min_value=0, decimal_places=2, initial=60, required=False
    )
    outlets = forms.MultipleChoiceField(
        label=gettext_lazy("Your outlets and services"), widget=forms.CheckboxSelectMultiple, required=False
    )

    def __init__(self, *args, **kwargs):
        from apps.core.models import HotelSettings
        from apps.core.setup import STARTER_OUTLETS

        super().__init__(*args, **kwargs)
        self.fields["business_type"].choices = HotelSettings.BusinessType.choices
        self.fields["outlets"].choices = [(k, v[0]) for k, v in STARTER_OUTLETS.items()]

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("modules"):
            raise forms.ValidationError(gettext_lazy("Choose at least one area of the app to use."))
        return cleaned
