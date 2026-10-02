from django import forms


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
                widget.attrs.setdefault("rows", 3)
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
