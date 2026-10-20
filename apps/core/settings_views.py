"""The settings hub: business details, receipts, modules, and backups."""

import base64
import secrets
from pathlib import Path
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth import logout
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required

from . import backup
from .forms import StyledFormMixin, TimeInput
from .models import HotelSettings, audit

MAX_LOGO_BYTES = 400 * 1024
LOGO_TYPES = {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}


class BusinessForm(StyledFormMixin, forms.ModelForm):
    full_width_fields = ("address",)

    class Meta:
        model = HotelSettings
        fields = [
            "name",
            "legal_name",
            "tax_status",
            "tax_id",
            "phone",
            "email",
            "address",
            "currency",
            "currency_symbol",
            "vat_rate",
            "default_language",
            "day_ends_at",
            "check_in_time",
            "check_out_time",
        ]
        widgets = {"check_in_time": TimeInput(), "check_out_time": TimeInput(), "tax_status": forms.RadioSelect(attrs={"data-full": "1"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.module_rooms:
            del self.fields["check_in_time"]
            del self.fields["check_out_time"]

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("tax_status")
        if status == HotelSettings.TaxStatus.VAT and not cleaned.get("vat_rate"):
            self.add_error("vat_rate", _("Enter the VAT rate, or choose “Registered, without VAT”."))
        if status != HotelSettings.TaxStatus.VAT:
            cleaned["vat_rate"] = Decimal("0")
        return cleaned


class ReceiptForm(StyledFormMixin, forms.ModelForm):
    logo_file = forms.FileField(
        label=gettext_lazy("Logo"),
        required=False,
        help_text=gettext_lazy("PNG, JPG, WEBP or SVG, up to 400 KB. Shown on receipts, invoices and the menu."),
    )
    remove_logo = forms.BooleanField(label=gettext_lazy("Remove the current logo"), required=False)

    class Meta:
        model = HotelSettings
        fields = [
            "receipt_header",
            "receipt_footer",
            "invoice_footer",
            "receipt_width",
            "receipt_show_logo",
            "receipt_show_vat",
            "max_staff_discount",
        ]

    def clean_logo_file(self):
        f = self.cleaned_data.get("logo_file")
        if not f:
            return None
        if f.size > MAX_LOGO_BYTES:
            raise forms.ValidationError(_("The logo is too large. Use an image under 400 KB."))
        if f.content_type not in LOGO_TYPES:
            raise forms.ValidationError(_("Use a PNG, JPG, WEBP or SVG image."))
        return f

    def save(self, commit=True):
        obj = super().save(commit=False)
        f = self.cleaned_data.get("logo_file")
        if self.cleaned_data.get("remove_logo"):
            obj.logo = ""
        elif f:
            obj.logo = f"data:{f.content_type};base64,{base64.b64encode(f.read()).decode('ascii')}"
        if commit:
            obj.save()
        return obj


class ModulesForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = [
            "business_type",
            "module_rooms",
            "module_housekeeping",
            "module_maintenance",
            "module_outlets",
            "module_inventory",
        ]
        widgets = {"business_type": forms.RadioSelect}

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(f) for f in ("module_rooms", "module_maintenance", "module_outlets")):
            raise forms.ValidationError(_("Switch on at least one area."))
        return cleaned


class BookingSettingsForm(StyledFormMixin, forms.ModelForm):
    full_width_fields = ("public_url",)

    class Meta:
        model = HotelSettings
        fields = [
            "booking_enabled",
            "booking_requires_confirmation",
            "public_url",
            "notify_email",
            "booking_deposit_percent",
            "booking_min_days_ahead",
            "booking_max_days_ahead",
            "booking_intro",
            "booking_terms",
            "bank_details",
        ]

    def clean_booking_deposit_percent(self):
        value = self.cleaned_data["booking_deposit_percent"]
        if value > 100:
            raise forms.ValidationError(gettext_lazy("Enter a value from 0 to 100."))
        return value


class EmailSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = ["smtp_host", "smtp_port", "smtp_security", "smtp_username", "smtp_password", "email_from"]
        widgets = {"smtp_password": forms.PasswordInput(render_value=True)}


class RemoteSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = ["tunnel_enabled", "tunnel_token"]
        widgets = {"tunnel_token": forms.PasswordInput(render_value=True, attrs={"autocomplete": "off", "data-full": "1"})}

    def clean(self):
        cleaned = super().clean()
        token = (cleaned.get("tunnel_token") or "").strip()
        if token.startswith("cloudflared") or " " in token:
            token = token.split()[-1]  # the whole install command was pasted: keep the token
        cleaned["tunnel_token"] = token
        if cleaned.get("tunnel_enabled") and len(token) < 80:
            self.add_error("tunnel_token", _("Paste the tunnel token from Cloudflare (a long text)."))
        return cleaned


class LoyaltySettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = ["loyalty_enabled", "loyalty_stamps", "vouchers_enabled", "voucher_months"]


class GuestMessagesForm(StyledFormMixin, forms.ModelForm):
    full_width_fields = ("message_pre_arrival_text", "message_review_text", "message_review_url")

    class Meta:
        model = HotelSettings
        fields = [
            "message_pre_arrival",
            "message_pre_arrival_days",
            "message_pre_arrival_text",
            "message_review",
            "message_review_url",
            "message_review_text",
            "message_hour",
        ]
        widgets = {
            "message_pre_arrival_text": forms.Textarea(attrs={"rows": 5}),
            "message_review_text": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("message_review") and not cleaned.get("message_review_url"):
            self.add_error("message_review_url", _("Paste the link where guests can leave a review."))
        return cleaned


class BreakfastForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = ["breakfast_on", "breakfast_included_default", "breakfast_price"]


class TouristTaxForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = ["tourist_tax_enabled", "tourist_tax_amount", "tourist_tax_basis", "tourist_tax_children", "tourist_tax_max_nights"]
        widgets = {"tourist_tax_basis": forms.RadioSelect()}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("tourist_tax_enabled") and not cleaned.get("tourist_tax_amount"):
            self.add_error("tourist_tax_amount", _("Enter the amount your municipality charges."))
        return cleaned


class TillSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = ["pin_lock_minutes"]


class SummarySettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = ["summary_to", "summary_hour"]
        widgets = {"summary_to": forms.TextInput(attrs={"placeholder": "owner@example.com", "data-full": "1"})}

    def clean_summary_to(self):
        from django.core.validators import validate_email

        addresses = [a.strip() for a in self.cleaned_data["summary_to"].replace(";", ",").split(",") if a.strip()]
        for a in addresses:
            try:
                validate_email(a)
            except forms.ValidationError:
                raise forms.ValidationError(_("“%(a)s” is not an email address.") % {"a": a})
        return ", ".join(addresses)


class PaymentSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = [
            "payment_provider",
            "payment_test_mode",
            "booking_card_deposit",
            "pok_merchant_id",
            "pok_key_id",
            "pok_key_secret",
            "paysera_project_id",
            "paysera_password",
        ]
        widgets = {
            "pok_key_secret": forms.PasswordInput(render_value=True),
            "paysera_password": forms.PasswordInput(render_value=True),
        }

    def clean(self):
        cleaned = super().clean()
        p = cleaned.get("payment_provider")
        need = {
            "pok": ("pok_merchant_id", "pok_key_id", "pok_key_secret"),
            "paysera": ("paysera_project_id", "paysera_password"),
        }
        for f in need.get(p, ()):
            if not cleaned.get(f):
                self.add_error(f, _("Needed for %(p)s.") % {"p": dict(self.fields["payment_provider"].choices)[p]})
        if p == "pok" and self.instance.currency not in ("ALL", "EUR"):
            raise forms.ValidationError(_("POK accepts only ALL and EUR. Change the currency in Business details."))
        return cleaned


class FiscalSettingsForm(StyledFormMixin, forms.ModelForm):
    certificate_file = forms.FileField(
        label=gettext_lazy("Digital certificate (.p12 / .pfx)"),
        required=False,
        help_text=gettext_lazy("The electronic seal certificate issued for fiscalization (from e-Albania / NAIS)."),
    )

    class Meta:
        model = HotelSettings
        fields = [
            "fiscal_enabled",
            "fiscal_test",
            "fiscal_business_unit",
            "fiscal_tcr_code",
            "fiscal_software_code",
            "fiscal_maintainer_code",
            "fiscal_operator_code",
            "fiscal_town",
            "vat_rate_accommodation",
            "fiscal_exchange_rate",
            "certificate_file",
            "fiscal_certificate_password",
        ]
        widgets = {"fiscal_certificate_password": forms.PasswordInput(render_value=True)}

    def clean(self):
        import base64

        from apps.fiscal.signing import Certificate, CertificateError

        cleaned = super().clean()
        upload = cleaned.get("certificate_file")
        password = cleaned.get("fiscal_certificate_password") or ""
        data = (
            upload.read()
            if upload
            else (base64.b64decode(self.instance.fiscal_certificate) if self.instance.fiscal_certificate else None)
        )
        if data:
            try:
                Certificate.from_p12(data, password)
            except CertificateError:
                self.add_error("fiscal_certificate_password", _("The certificate can't be opened with this password."))
            else:
                self.instance.fiscal_certificate = base64.b64encode(data).decode()
        if cleaned.get("fiscal_enabled"):
            if not self.instance.registered:
                raise forms.ValidationError(_("Fiscalization is for businesses registered with the tax authority (Business details)."))
            if self.instance.demo_data:
                raise forms.ValidationError(_("Remove the sample data first (the banner at the top), then set up your own business."))
            if not self.instance.tax_id:
                raise forms.ValidationError(_("Enter the NIPT in Business details first."))
            for f in ("fiscal_business_unit", "fiscal_tcr_code", "fiscal_software_code", "fiscal_operator_code"):
                if not cleaned.get(f):
                    self.add_error(f, _("Needed to fiscalize."))
            if not data:
                self.add_error("certificate_file", _("Upload the certificate."))
            if (self.instance.currency or "ALL").upper() != "ALL" and not cleaned.get("fiscal_exchange_rate"):
                self.add_error(
                    "fiscal_exchange_rate",
                    _("Your prices are in %(c)s: the tax authority needs the rate to lekë.") % {"c": self.instance.currency},
                )
            if not self.instance.fiscal_enabled or not self.instance.fiscal_since:
                # Turned on now (the instance still holds the saved values): sales from here on are
                # checked for a fiscal receipt, never the ones made while it was off.
                from django.utils import timezone

                self.instance.fiscal_since = timezone.now()
        return cleaned


class SyncSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = ["sync_enabled", "sync_folder", "sync_every", "sync_password"]
        widgets = {"sync_password": forms.PasswordInput(render_value=True, attrs={"autocomplete": "new-password"})}

    def clean(self):
        from . import sync

        cleaned = super().clean()
        cleaned["sync_folder"] = (cleaned.get("sync_folder") or "").strip()
        if cleaned.get("sync_enabled") or cleaned["sync_folder"]:
            problem = sync.check_folder(cleaned["sync_folder"])
            if problem:
                self.add_error("sync_folder", problem)
        return cleaned


TABS = {
    "fiscal": FiscalSettingsForm,
    "payments": PaymentSettingsForm,
    "business": BusinessForm,
    "receipts": ReceiptForm,
    "modules": ModulesForm,
    "booking": BookingSettingsForm,
    "email": EmailSettingsForm,
    "tills": TillSettingsForm,
    "loyalty": LoyaltySettingsForm,
    "tourist_tax": TouristTaxForm,
    "breakfast": BreakfastForm,
    "messages": GuestMessagesForm,
    "remote": RemoteSettingsForm,
}


@module_required("management")
def settings_hub(request):
    tab = request.GET.get("tab", "business")
    hs = HotelSettings.load()
    if tab == "fiscal" and not hs.registered:
        messages.info(request, _("Fiscalization is for businesses registered with the tax authority (Business details)."))
        return redirect(f"{request.path}?tab=business")
    ctx = {"tab": tab}
    if tab in TABS:
        form = TABS[tab](request.POST or None, request.FILES or None, instance=hs)
        if request.method == "POST" and form.is_valid():
            form.save()
            audit(request.user, f"settings.{tab}", hs.name, hs)
            messages.success(request, _("Settings saved."))
            return redirect(f"{request.path}?tab={tab}")
        ctx["form"] = form
        if tab == "fiscal" and hs.fiscal_certificate:
            from apps.fiscal.signing import Certificate, CertificateError

            try:
                ctx["certificate"] = Certificate.from_settings(hs)
            except CertificateError as e:
                ctx["certificate_error"] = str(e)
        if tab == "remote":
            from apps.outlets.menu import qr_svg

            from . import remote

            addresses = remote.local_addresses()
            ts = remote.tailscale_address(addresses)
            lan = remote.lan_address(addresses)
            ctx.update(
                windows_app=remote.is_windows_app(),
                port=remote.port(),
                lan_url=f"http://{lan}:{remote.port()}/" if lan else "",
                tailscale_url=f"http://{ts}:{remote.port()}/" if ts else "",
                tailscale_qr=qr_svg(f"http://{ts}:{remote.port()}/") if ts else "",
                tunnel=remote.read_status(),
            )
        if tab == "tills":
            from apps.accounts.models import User

            ctx["pin_staff"] = User.objects.filter(is_active=True).exclude(username__startswith="sample.")
        if tab == "messages":
            from apps.frontdesk import guest_messages as gm
            from apps.frontdesk.models import Guest, Reservation

            sample = Reservation(guest=Guest(first_name=_("Ana")), arrival=timezone.localdate() + timedelta(days=hs.message_pre_arrival_days), departure=timezone.localdate() + timedelta(days=hs.message_pre_arrival_days + 2))
            ctx["preview_arrival"] = gm.text(gm.PRE_ARRIVAL, sample, hs)
            ctx["preview_review"] = gm.text(gm.REVIEW, sample, hs)
        if tab == "email":
            ctx["summary_form"] = SummarySettingsForm(instance=hs)
        if tab == "booking":
            from django.urls import reverse

            from apps.outlets.menu import public_link

            ctx["booking_link"] = public_link(request, reverse("booking:search"))
    elif tab == "group":
        from . import remote
        from .models import GroupMember

        addresses = remote.local_addresses()
        found = [f"http://{a}:{remote.port()}" for a in filter(None, [remote.tailscale_address(addresses), remote.lan_address(addresses)])]
        if hs.public_url:
            found.insert(0, hs.public_url.rstrip("/"))
        ctx.update(group_addresses=found, group_members=GroupMember.objects.all())
    elif tab == "import":
        from . import importer

        ctx["import_kinds"] = [(k, v["label"], v["columns"], v["required"]) for k, v in importer.KINDS.items()]
    elif tab == "backup":
        from . import sync

        ctx["disk_backups"] = backup.disk_backups()
        ctx["backup_dir"] = backup.backup_dir()
        ctx["sync_form"] = SyncSettingsForm(instance=hs)
        ctx["sync_status"] = sync.status(hs)
        ctx["sync_copies"] = sync.copies(hs.sync_folder, limit=15) if hs.sync_folder else []
        ctx["sync_suggestions"] = sync.suggestions()
    else:
        raise Http404
    return render(request, "core/settings_hub.html", ctx)


@require_POST
@module_required("management")
def sync_settings(request):
    """Save the automatic copy settings, then make a first copy straight away so problems show now."""
    from . import sync

    hs = HotelSettings.load()
    form = SyncSettingsForm(request.POST, instance=hs)
    if not form.is_valid():
        ctx = {
            "tab": "backup",
            "disk_backups": backup.disk_backups(),
            "backup_dir": backup.backup_dir(),
            "sync_form": form,
            "sync_status": sync.status(hs),
            "sync_copies": [],
            "sync_suggestions": sync.suggestions(),
        }
        return render(request, "core/settings_hub.html", ctx)
    form.save()
    audit(request.user, "settings.sync", f"{hs.sync_folder} ({'on' if hs.sync_enabled else 'off'})", hs)
    if hs.sync_enabled:
        try:
            path = sync.run(force=True)
            messages.success(request, _("Saved. First copy written: %(name)s") % {"name": path.name})
        except sync.SyncError as e:
            messages.error(request, _("Saved, but the copy failed: %(e)s") % {"e": e})
    else:
        messages.success(request, _("Settings saved."))
    return redirect("/settings/?tab=backup#sync")


@require_POST
@module_required("management")
def sync_now(request):
    from . import sync

    try:
        path = sync.run(force=True)
        audit(request.user, "backup.copy", path.name)
        messages.success(request, _("Copy written: %(name)s") % {"name": path.name})
    except sync.SyncError as e:
        messages.error(request, _("The copy failed: %(e)s") % {"e": e})
    return redirect("/settings/?tab=backup#sync")


@module_required("management")
def restore_from_copy(request):
    """Bring a copy from the other place into InnKeeper's backup folder, then restore it as usual."""
    import shutil

    from . import sync

    name = request.GET.get("name", "")
    folder = Path(HotelSettings.load().sync_folder or "")
    path = folder / name
    if not name or "/" in name or "\\" in name or not name.startswith(sync.PREFIX) or not path.is_file():
        raise Http404
    local = f"copy-{name}"
    shutil.copyfile(path, backup.backup_dir() / local)
    return redirect(f"/settings/restore/?file={local}")


@module_required("management")
def backup_download(request, kind):
    if kind == "full":
        data = backup.export_full()
    elif kind == "settings":
        data = backup.export_settings()
    else:
        raise Http404
    audit(request.user, f"backup.download_{kind}", backup.filename(kind))
    response = HttpResponse(data, content_type="application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="{backup.filename(kind)}"'
    return response


@require_POST
@module_required("management")
def backup_now(request):
    path = backup.save_backup_to_disk("manual", keep=0)
    audit(request.user, "backup.save", path.name)
    messages.success(request, _("Backup saved: %(name)s") % {"name": path.name})
    return redirect("/settings/?tab=backup")


@module_required("management")
def backup_file(request, name):
    path = backup.backup_dir() / name
    if "/" in name or "\\" in name or not path.is_file() or path.suffix != ".innkeeper":
        raise Http404
    return FileResponse(path.open("rb"), as_attachment=True, filename=name)


@module_required("management")
def restore(request):
    """Step 1: upload (or pick a saved backup) and see what's inside. Step 2: confirm.
    Password-protected copies ask for their password first and are unlocked into a normal backup."""
    if request.method == "POST" and request.FILES.get("file"):
        raw = request.FILES["file"].read()
        name = f"upload-{secrets.token_hex(4)}.innkeeper"
        (backup.backup_dir() / name).write_bytes(raw)
    else:
        name = request.POST.get("file") or request.GET.get("file", "")
        path = backup.backup_dir() / name
        if not name or "/" in name or "\\" in name or not path.is_file():
            return redirect("/settings/?tab=backup")
        raw = path.read_bytes()
    if backup.is_encrypted(raw):
        password = request.POST.get("password", "")
        if not password:
            return render(request, "core/restore_password.html", {"file": name})
        try:
            raw = backup.decrypt(raw, password)
        except backup.BackupError:
            return render(request, "core/restore_password.html", {"file": name, "wrong": True})
        if name.startswith(("upload-", "copy-")):
            (backup.backup_dir() / name).unlink(missing_ok=True)
        name = f"upload-{secrets.token_hex(4)}.innkeeper"
        (backup.backup_dir() / name).write_bytes(raw)
    try:
        doc = backup.read_file(raw)
    except backup.BackupError:
        if name.startswith(("upload-", "copy-")):
            (backup.backup_dir() / name).unlink(missing_ok=True)
        messages.error(request, _("This file is not an InnKeeper backup."))
        return redirect("/settings/?tab=backup")
    return render(request, "core/restore_confirm.html", {"summary": backup.summarize(doc), "file": name})


@require_POST
@module_required("management")
def restore_confirm(request):
    name = request.POST.get("file", "")
    path = backup.backup_dir() / name
    if not name or "/" in name or "\\" in name or not path.is_file():
        raise Http404
    doc = backup.read_file(path.read_bytes())
    if doc["kind"] == "settings":
        stats = backup.import_settings(doc)
        audit(request.user, "backup.import_settings", str(stats))
        messages.success(
            request,
            _("Settings imported: %(o)s outlets, %(i)s menu items, %(t)s tables, %(r)s rooms.")
            % {"o": stats["outlets"], "i": stats["items"], "t": stats["tables"], "r": stats["rooms"]},
        )
        if name.startswith(("upload-", "copy-")):
            path.unlink(missing_ok=True)
        return redirect("/settings/?tab=backup")

    if request.POST.get("confirm_text", "").strip().upper() not in {"RESTORE", "RIKTHE"}:
        messages.error(request, _("Type RESTORE to confirm."))
        return redirect(f"/settings/restore/?file={name}")
    safety = backup.save_backup_to_disk("before-restore", keep=10)
    backup.restore_full(doc)
    if name.startswith(("upload-", "copy-")):
        path.unlink(missing_ok=True)
    logout(request)
    messages.success(
        request,
        _(
            "Backup restored. Sign in with an account from the restored data. A copy of the previous data was saved as %(name)s."
        )
        % {"name": safety.name},
    )
    return redirect("accounts:login")


@require_POST
@module_required("management")
def summary_settings(request):
    hs = HotelSettings.load()
    form = SummarySettingsForm(request.POST, instance=hs)
    if form.is_valid():
        form.save()
        audit(request.user, "settings.summary", hs.summary_to or "-", hs)
        messages.success(request, _("Settings saved."))
    else:
        for errors in form.errors.values():
            for e in errors:
                messages.error(request, e)
    return redirect("/settings/?tab=email")


@require_POST
@module_required("management")
def summary_send_now(request):
    """Send the summary of the last business day now, to check how it looks."""
    from apps.core.businessday import business_date
    from apps.finance import summary

    hs = HotelSettings.load()
    if not hs.email_configured:
        messages.error(request, _("Fill in and save the email settings first."))
    elif not hs.summary_recipients:
        messages.error(request, _("Add the email address the summary goes to first."))
    else:
        day = business_date() - timedelta(days=1)
        if summary.send(day, force=True):
            messages.success(request, _("Summary of %(d)s sent to %(to)s.") % {"d": day.strftime("%d.%m.%Y"), "to": hs.summary_to})
        else:
            messages.error(request, _("The email could not be sent. Check the server, port, security, username and password."))
    return redirect("/settings/?tab=email")


@require_POST
@module_required("management")
def email_test(request):
    from . import email

    hs = HotelSettings.load()
    to = request.user.email or hs.email or hs.email_from
    if not hs.email_configured:
        messages.error(request, _("Fill in and save the email settings first."))
    elif not to:
        messages.error(request, _("Add an email address to your staff account or the business details first."))
    elif email.send(to, _("InnKeeper test email"), "booking/email_test.html", {}):
        messages.success(request, _("Test email sent to %(to)s.") % {"to": to})
    else:
        messages.error(
            request, _("The email could not be sent. Check the server, port, security, username and password.")
        )
    return redirect("/settings/?tab=email")


# ---------- Import from Excel (.xlsx) or CSV ----------


@module_required("management")
def import_template(request, kind):
    from . import importer, spreadsheet

    if kind not in importer.KINDS:
        raise Http404
    if request.GET.get("format") == "csv":
        response = HttpResponse("\ufeff" + importer.template_csv(kind), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="innkeeper-{kind}.csv"'
        return response
    response = HttpResponse(importer.template_xlsx(kind), content_type=spreadsheet.XLSX_TYPE)
    response["Content-Disposition"] = f'attachment; filename="innkeeper-{kind}.xlsx"'
    return response


@module_required("management")
def import_file(request):
    """Step 1: upload and preview. Step 2 (confirm): import the same file."""
    from . import importer

    kind = request.POST.get("kind", "")
    if request.method != "POST" or kind not in importer.KINDS:
        return redirect("/settings/?tab=import")
    if request.POST.get("confirm") == "1":
        name = request.POST.get("file", "")
        path = backup.backup_dir() / name
        if not name.startswith("import-") or "/" in name or "\\" in name or not path.is_file():
            return redirect("/settings/?tab=import")
        parsed = importer.parse(kind, path.read_bytes())
        path.unlink(missing_ok=True)
        if not parsed.rows:
            messages.error(request, _("Nothing to import."))
            return redirect("/settings/?tab=import")
        stats = importer.apply(parsed, request.user)
        messages.success(
            request, _("Imported: %(c)s new, %(u)s updated.") % {"c": stats["created"], "u": stats["updated"]}
        )
        return redirect("/settings/?tab=import")
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, _("Choose a file."))
        return redirect("/settings/?tab=import")
    raw = upload.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        messages.error(request, _("The file is too large (5 MB at most)."))
        return redirect("/settings/?tab=import")
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        messages.error(request, _("This is an old Excel file (.xls). In Excel choose File → Save as → “Excel Workbook (.xlsx)”, then upload that."))
        return redirect("/settings/?tab=import")
    parsed = importer.parse(kind, raw)
    name = f"import-{secrets.token_hex(6)}.{'xlsx' if raw[:2] == b'PK' else 'csv'}"
    (backup.backup_dir() / name).write_bytes(raw)
    cols = importer.KINDS[kind]["columns"]
    return render(
        request,
        "core/import_preview.html",
        {
            "kind": kind,
            "label": importer.KINDS[kind]["label"],
            "parsed": parsed,
            "file": name,
            "columns": [c for c in cols if c in parsed.columns],
            "preview": parsed.rows[:20],
        },
    )
