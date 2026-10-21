"""
Invoice to a company: the buyer's name and NUIS on a guest bill or a restaurant/bar bill. They are printed on
the invoice and sent to the tax authority as the Buyer of the fiscal invoice (IDType NUIS).

Invoices paid by bank transfer between businesses must also be sent as an electronic invoice (e-faturë)
through the tax authority's central platform; until InnKeeper does that itself, issue the e-invoice from the
self-care portal (the bill shows a reminder).
"""

import re

from django import forms
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

NUIS_RE = re.compile(r"^[A-Z]\d{8}[A-Z]$")
NONCASH_METHODS = {"bank_transfer", "other"}


def clean_nuis(value: str) -> str:
    v = (value or "").strip().upper().replace(" ", "")
    if v and not NUIS_RE.match(v):
        raise forms.ValidationError(_("A NUIS has a letter, 8 digits and a letter, e.g. L12345678A."))
    return v


class BuyerForm(forms.Form):
    buyer_name = forms.CharField(label=gettext_lazy("Company name"), max_length=100, required=False)
    buyer_nuis = forms.CharField(label=gettext_lazy("NUIS"), max_length=20, required=False)
    buyer_address = forms.CharField(label=gettext_lazy("Address"), max_length=200, required=False)
    buyer_town = forms.CharField(label=gettext_lazy("Town"), max_length=60, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs["class"] = "input"
        self.fields["buyer_nuis"].widget.attrs.update({"autocomplete": "off", "style": "text-transform:uppercase"})

    def clean_buyer_nuis(self):
        return clean_nuis(self.cleaned_data.get("buyer_nuis", ""))

    def clean(self):
        cleaned = super().clean()
        name, nuis = (cleaned.get("buyer_name") or "").strip(), cleaned.get("buyer_nuis") or ""
        if nuis and not name:
            self.add_error("buyer_name", _("Enter the company name."))
        if name and not nuis:
            self.add_error("buyer_nuis", _("Enter the company's NUIS."))
        return cleaned


def save(obj, form: BuyerForm) -> None:
    d = form.cleaned_data
    obj.buyer_name = (d.get("buyer_name") or "").strip()
    obj.buyer_nuis = d.get("buyer_nuis") or ""
    obj.buyer_address = (d.get("buyer_address") or "").strip() if obj.buyer_nuis else ""
    obj.buyer_town = (d.get("buyer_town") or "").strip() if obj.buyer_nuis else ""
    if not obj.buyer_nuis:
        obj.buyer_name = ""
    obj.save(update_fields=["buyer_name", "buyer_nuis", "buyer_address", "buyer_town"])


def payload(obj) -> dict | None:
    """The Buyer of the fiscal invoice, or None for a private customer."""
    if not getattr(obj, "buyer_nuis", ""):
        return None
    return {
        "IDType": "NUIS",
        "IDNum": obj.buyer_nuis,
        "Name": obj.buyer_name[:100],
        "Address": (obj.buyer_address or "-")[:400],
        "Town": (obj.buyer_town or "-")[:100],
        "Country": "ALB",
    }


def needs_einvoice(obj, payments) -> bool:
    """A company paying by bank transfer (or another non-cash way): an e-invoice is required."""
    return bool(getattr(obj, "buyer_nuis", "")) and any(p.method in NONCASH_METHODS for p in payments if not p.voided)
