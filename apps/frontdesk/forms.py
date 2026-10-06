from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.forms import DateInput, StyledFormMixin
from apps.finance.models import Payment

from .models import Guest, Reservation, Room, RoomType, SeasonRate


class GuestForm(StyledFormMixin, forms.ModelForm):
    full_width_fields = ("address",)

    class Meta:
        model = Guest
        fields = [
            "first_name",
            "last_name",
            "phone",
            "email",
            "nationality",
            "date_of_birth",
            "document_type",
            "document_number",
            "company",
            "address",
            "is_vip",
            "notes",
        ]
        widgets = {"date_of_birth": DateInput()}


class RoomChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, room):
        label = f"{room.number} · {room.room_type.name} · {room.room_type.base_rate:.2f}"
        if room.out_of_order:
            label += f" ({_('out of order')})"
        return label


class ReservationForm(StyledFormMixin, forms.ModelForm):
    """Book a room for an existing guest or a new one."""

    guest = forms.ModelChoiceField(
        label=_("Existing guest"),
        queryset=Guest.objects.all(),
        required=False,
        widget=forms.HiddenInput,
        help_text=_("Search for a returning guest, or fill in the new guest's name below."),
    )
    new_first_name = forms.CharField(label=_("First name"), required=False, max_length=80)
    new_last_name = forms.CharField(label=_("Last name"), required=False, max_length=80)
    new_phone = forms.CharField(label=_("Phone"), required=False, max_length=40)
    new_email = forms.EmailField(label=_("Email"), required=False)
    room = RoomChoiceField(label=_("Room"), queryset=Room.objects.none())
    rate = forms.DecimalField(
        label=_("Nightly rate"),
        required=False,
        min_value=Decimal("0"),
        decimal_places=2,
        help_text=_("Leave empty to use the price list (room type rate and seasons)."),
    )

    class Meta:
        model = Reservation
        fields = ["room", "arrival", "departure", "adults", "children", "rate", "source", "external_ref", "notes"]
        widgets = {"arrival": DateInput(), "departure": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = Room.objects.filter(is_active=True).select_related("room_type")
        if self.instance.pk:
            for name in ("guest", "new_first_name", "new_last_name", "new_phone", "new_email"):
                del self.fields[name]
            if self.instance.nightly_rates:
                # Priced from the price list: keep it automatic unless someone types a rate.
                self.initial["rate"] = None
        else:
            self.order_fields(["guest", "new_first_name", "new_last_name", "new_phone", "new_email"])

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk:
            guest = cleaned.get("guest")
            first, last = cleaned.get("new_first_name", "").strip(), cleaned.get("new_last_name", "").strip()
            if not guest and not (first and last):
                raise forms.ValidationError(_("Choose an existing guest or enter the new guest's first and last name."))
        room, arrival, departure = cleaned.get("room"), cleaned.get("arrival"), cleaned.get("departure")
        self.quote = None
        if cleaned.get("rate") is None and room and arrival and departure and departure > arrival:
            from .pricing import apply_quote, quote

            self.quote = quote(room.room_type, arrival, departure)
            apply_quote(self.instance, self.quote)
            cleaned["rate"] = self.instance.rate
        elif cleaned.get("rate") is not None:
            self.instance.nightly_rates = []
        return cleaned

    def _post_clean(self):
        nightly = self.instance.nightly_rates
        super()._post_clean()
        self.instance.nightly_rates = nightly

    def get_guest(self) -> Guest:
        if self.instance.pk:
            return self.instance.guest
        guest = self.cleaned_data.get("guest")
        if guest:
            return guest
        return Guest.objects.create(
            first_name=self.cleaned_data["new_first_name"].strip(),
            last_name=self.cleaned_data["new_last_name"].strip(),
            phone=self.cleaned_data.get("new_phone", "").strip(),
            email=self.cleaned_data.get("new_email", "").strip(),
        )


class ChargeForm(StyledFormMixin, forms.Form):
    description = forms.CharField(label=_("Description"), max_length=200)
    quantity = forms.IntegerField(label=_("Qty"), min_value=1, initial=1)
    unit_price = forms.DecimalField(label=_("Price"), min_value=Decimal("0"), decimal_places=2)


class PaymentForm(StyledFormMixin, forms.Form):
    amount = forms.DecimalField(label=_("Amount"), decimal_places=2, help_text=_("Use a negative amount for a refund."))
    method = forms.ChoiceField(label=_("Method"), choices=Payment.Method.choices)
    reference = forms.CharField(label=_("Reference"), max_length=80, required=False)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount == 0:
            raise forms.ValidationError(_("Enter an amount."))
        return amount


class VoidForm(forms.Form):
    reason = forms.CharField(max_length=255)


class RoomForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Room
        fields = ["number", "room_type", "floor", "hk_status", "notes", "is_active"]
        help_texts = {"is_active": _("Inactive rooms are hidden from the rack and cannot be booked.")}


class RoomTypeForm(StyledFormMixin, forms.ModelForm):
    photo_file = forms.FileField(
        label=_("Photo"),
        required=False,
        help_text=_("Shown on the online booking page. JPG or PNG, up to 600 KB (a 1200 px wide photo is plenty)."),
    )
    remove_photo = forms.BooleanField(label=_("Remove the current photo"), required=False)

    class Meta:
        model = RoomType
        fields = [
            "name",
            "code",
            "base_rate",
            "max_adults",
            "max_children",
            "description",
            "name_en",
            "description_en",
            "bookable_online",
            "sort_order",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.photo:
            del self.fields["remove_photo"]

    def clean_photo_file(self):
        from apps.core.forms import image_to_data_uri

        f = self.cleaned_data.get("photo_file")
        return image_to_data_uri(f, 600) if f else None

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("remove_photo"):
            obj.photo = ""
        elif self.cleaned_data.get("photo_file"):
            obj.photo = self.cleaned_data["photo_file"]
        if commit:
            obj.save()
        return obj


class SeasonRateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SeasonRate
        fields = ["name", "room_type", "start_date", "end_date", "percent", "rate", "min_nights", "is_active"]
        widgets = {"start_date": DateInput(), "end_date": DateInput()}
