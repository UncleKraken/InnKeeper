
from django import forms
from django.contrib import messages
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.accounts.forms import _client_ip
from apps.accounts.permissions import module_required
from apps.core.exceptions import BusinessError
from apps.core.forms import StyledFormMixin
from apps.core.models import HotelSettings, audit

from . import services
from .models import Campaign, Contact

TABS = [
    ("marketing:contacts", gettext_lazy("Contacts")),
    ("marketing:campaigns", gettext_lazy("Email campaigns")),
    ("marketing:signup_poster", gettext_lazy("Sign-up QR")),
]


def _filtered(request):
    qs = Contact.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q) | Q(tags__icontains=q))
    show = request.GET.get("show", "")
    if show == "ok":
        qs = qs.filter(marketing_ok=True, unsubscribed_at__isnull=True)
    elif show == "no":
        qs = qs.filter(marketing_ok=False, unsubscribed_at__isnull=True)
    elif show == "unsub":
        qs = qs.filter(unsubscribed_at__isnull=False)
    source = request.GET.get("source", "")
    if source in Contact.Source.values:
        qs = qs.filter(source=source)
    return qs, q, show, source


@module_required("management")
def contacts(request):
    qs, q, show, source = _filtered(request)
    fmt = request.GET.get("format")
    if fmt in ("csv", "xlsx", "whatsapp"):
        return _export(request, qs, fmt)
    counts = Contact.objects.aggregate(
        total=Count("id"),
        ok=Count("id", filter=Q(marketing_ok=True, unsubscribed_at__isnull=True)),
        unsub=Count("id", filter=Q(unsubscribed_at__isnull=False)),
    )
    page = Paginator(qs.order_by("name"), 50).get_page(request.GET.get("page"))
    return render(
        request,
        "marketing/contacts.html",
        {"page_obj": page, "q": q, "show": show, "source": source, "sources": Contact.Source.choices, "counts": counts,
         "query": request.GET.urlencode(), "tabs": TABS, "tab": "marketing:contacts"},
    )


def _export(request, qs, fmt):
    audit(request.user, "marketing.export", f"{fmt}: {qs.count()}")
    if fmt == "whatsapp":
        # Only people who agreed; one number a line, to add to a WhatsApp Business broadcast list.
        nums = sorted({services.phone_key(c.phone) for c in qs.filter(marketing_ok=True, unsubscribed_at__isnull=True) if services.phone_key(c.phone)})
        return HttpResponse("\n".join("+" + n for n in nums) + "\n", content_type="text/plain; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="whatsapp-numbers.txt"'})
    header = [_("Name"), _("Email"), _("Phone"), _("Language"), _("From"), _("Agreed to offers"), _("Agreed on"), _("How"), _("Tags"), _("Last visit")]
    rows = [
        [c.name, c.email, c.phone, c.language, c.get_source_display(), _("Yes") if c.marketing_ok and not c.unsubscribed_at else _("No"),
         timezone.localtime(c.consent_at).strftime("%d.%m.%Y %H:%M") if c.consent_at else "", c.consent_note, c.tags,
         c.last_seen.strftime("%d.%m.%Y") if c.last_seen else ""]
        for c in qs.order_by("name")
    ]
    if fmt == "xlsx":
        from apps.core import spreadsheet

        return spreadsheet.response("contacts", spreadsheet.Sheet(_("Contacts"), header, rows))
    from apps.core.models import SafeCSVWriter

    response = HttpResponse(content_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="contacts.csv"'})
    response.write("﻿")
    w = SafeCSVWriter(response)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return response


@require_POST
@module_required("management")
def sync(request):
    n = services.sync_all()
    audit(request.user, "marketing.sync", str(n))
    messages.success(request, _("Contacts updated: %(n)s new.") % {"n": n})
    return redirect("marketing:contacts")


class ContactForm(StyledFormMixin, forms.ModelForm):
    full_width_fields = ("notes",)

    class Meta:
        model = Contact
        fields = ["name", "email", "phone", "language", "tags", "marketing_ok", "consent_note", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["consent_note"].help_text = _("When they agreed: e.g. “signed form at reception 12.05”, “asked by phone”.")
        if self.instance.unsubscribed_at:
            self.fields["marketing_ok"].disabled = True
            self.fields["marketing_ok"].help_text = _("They unsubscribed on %(d)s. Only they can sign up again (sign-up page or booking form).") % {
                "d": timezone.localtime(self.instance.unsubscribed_at).strftime("%d.%m.%Y")}

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("email") and not cleaned.get("phone"):
            raise forms.ValidationError(_("Enter an email or a phone number."))
        newly = cleaned.get("marketing_ok") and not (self.instance.pk and self.instance.marketing_ok)
        if newly and not cleaned.get("consent_note", "").strip():
            self.add_error("consent_note", _("Write how they agreed: the law asks you to be able to show it."))
        return cleaned


@module_required("management")
def contact_form(request, pk=None):
    contact = get_object_or_404(Contact, pk=pk) if pk else Contact(source=Contact.Source.MANUAL)
    was_ok = contact.marketing_ok
    form = ContactForm(request.POST or None, instance=contact)
    if request.method == "POST":
        if request.POST.get("delete") == "1" and contact.pk:
            audit(request.user, "marketing.delete", contact.name)
            contact.delete()
            messages.success(request, _("Contact deleted."))
            return redirect("marketing:contacts")
        if form.is_valid():
            c = form.save(commit=False)
            if c.marketing_ok and not was_ok:
                c.consent_at = timezone.now()
            if not c.marketing_ok:
                c.consent_at = None if not was_ok else c.consent_at
            c.save()
            audit(request.user, "marketing.contact", c.name, c)
            messages.success(request, _("Saved."))
            return redirect("marketing:contacts")
    received = contact.received.select_related("campaign").order_by("-pk")[:10] if contact.pk else []
    return render(request, "marketing/contact_form.html", {"form": form, "contact": contact, "received": received, "tabs": TABS, "tab": "marketing:contacts"})


# ---------- Campaigns ----------


class CampaignForm(StyledFormMixin, forms.ModelForm):
    full_width_fields = ("subject", "body")

    class Meta:
        model = Campaign
        fields = ["subject", "body", "audience", "tag"]
        widgets = {"body": forms.Textarea(attrs={"rows": 10})}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("audience") == Campaign.Audience.TAG and not cleaned.get("tag", "").strip():
            self.add_error("tag", _("Write the tag."))
        return cleaned


@module_required("management")
def campaigns(request):
    rows = Campaign.objects.annotate(
        n=Count("recipients"), sent=Count("recipients", filter=Q(recipients__status="sent")),
        failed=Count("recipients", filter=Q(recipients__status="failed")),
    )
    return render(request, "marketing/campaigns.html", {"campaigns": rows, "tabs": TABS, "tab": "marketing:campaigns"})


@module_required("management")
def campaign_form(request, pk=None):
    campaign = get_object_or_404(Campaign, pk=pk) if pk else Campaign()
    if campaign.pk and campaign.status != Campaign.Status.DRAFT:
        return redirect("marketing:campaign_detail", pk=campaign.pk)
    form = CampaignForm(request.POST or None, instance=campaign)
    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        c.created_by = c.created_by or request.user
        c.save()
        return redirect("marketing:campaign_detail", pk=c.pk)
    return render(request, "marketing/campaign_form.html", {"form": form, "campaign": campaign, "tabs": TABS, "tab": "marketing:campaigns"})


@module_required("management")
def campaign_detail(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    counts = campaign.recipients.aggregate(
        total=Count("id"), sent=Count("id", filter=Q(status="sent")), failed=Count("id", filter=Q(status="failed")),
        pending=Count("id", filter=Q(status="pending")),
    )
    if campaign.status == Campaign.Status.SENDING and counts["pending"]:
        services.kick()  # e.g. after a restart
    sample = Contact(name=_("Ana"), language="sq")
    hs = HotelSettings.load()
    return render(
        request,
        "marketing/campaign_detail.html",
        {"campaign": campaign, "counts": counts, "audience_count": services.audience(campaign).count() if campaign.status == "draft" else None,
         "sample": sample, "ready": hs.email_configured and bool(services.public_base()), "tabs": TABS, "tab": "marketing:campaigns"},
    )


@require_POST
@module_required("management")
def campaign_send(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if request.POST.get("delete") == "1" and campaign.status == Campaign.Status.DRAFT:
        campaign.delete()
        return redirect("marketing:campaigns")
    if request.POST.get("test"):
        if not request.user.email:
            messages.error(request, _("Add your own email to your account first."))
        else:
            from apps.core import email

            ok = email.send(request.user.email, "[TEST] " + campaign.subject, "marketing/email_campaign.html",
                            {"campaign": campaign, "contact": Contact(name=request.user.get_full_name() or str(request.user)), "unsubscribe": "#"})
            (messages.success if ok else messages.error)(request, _("Test sent to %(e)s.") % {"e": request.user.email} if ok else _("The test email could not be sent. Check Settings → Email."))
        return redirect("marketing:campaign_detail", pk=pk)
    try:
        n = services.start(campaign, request.user)
        messages.success(request, _("Sending to %(n)s people. You can leave this page.") % {"n": n})
    except BusinessError as e:
        messages.error(request, str(e))
    return redirect("marketing:campaign_detail", pk=pk)


@module_required("management")
def signup_poster(request):
    from apps.outlets.menu import public_link, qr_svg

    url = public_link(request, reverse("news:signup"))
    return render(request, "marketing/poster.html", {"url": url, "qr": qr_svg(url), "tabs": TABS, "tab": "marketing:signup_poster"})


# ---------- Public pages ----------


class SignupForm(StyledFormMixin, forms.Form):
    name = forms.CharField(label=gettext_lazy("Name"), max_length=160)
    email = forms.EmailField(label=gettext_lazy("Email"))
    phone = forms.CharField(label=gettext_lazy("Phone (optional)"), max_length=40, required=False)
    agree = forms.BooleanField(label=gettext_lazy("Yes, send me news and offers. I can unsubscribe at any time."))
    website = forms.CharField(required=False, widget=forms.HiddenInput)  # left empty by people, filled by some bots

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("spam")
        return ""


def _lang(request) -> str:
    lang = request.GET.get("lang") or request.POST.get("lang") or translation.get_language() or "sq"
    return "en" if lang.startswith("en") else "sq"


@xframe_options_sameorigin
def signup(request):
    lang = _lang(request)
    translation.activate(lang)
    form = SignupForm(request.POST or None)
    done = False
    if request.method == "POST" and form.is_valid():
        key = f"innkeeper:signup:{_client_ip(request)}"
        if cache.get(key, 0) >= 10:
            form.add_error(None, _("Too many sign-ups from this connection. Please try later."))
        else:
            d = form.cleaned_data
            services.upsert(name=d["name"], email_=d["email"], phone=d["phone"], source="signup", language=lang, consent=True,
                            consent_note=_("Sign-up page, %(ip)s") % {"ip": _client_ip(request)})
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, 3600)
            done = True
    return render(request, "marketing/signup.html", {"form": form, "done": done, "lang": lang})


@xframe_options_sameorigin
def unsubscribe(request, token):
    contact = Contact.objects.filter(token=token).first()
    if contact is None or len(token) < 16:
        raise Http404
    lang = contact.language or _lang(request)
    translation.activate(lang)
    if request.method == "POST":
        services.unsubscribe(contact)
    return render(request, "marketing/unsubscribe.html", {"contact": contact, "done": contact.unsubscribed_at is not None, "lang": lang})
