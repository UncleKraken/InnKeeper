"""The settings hub: business details, receipts, modules, and backups."""

import base64
import secrets

from django import forms
from django.contrib import messages
from django.contrib.auth import logout
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
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
            "tax_id",
            "phone",
            "email",
            "address",
            "currency",
            "currency_symbol",
            "vat_rate",
            "default_language",
            "check_in_time",
            "check_out_time",
        ]
        widgets = {"check_in_time": TimeInput(), "check_out_time": TimeInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.module_rooms:
            del self.fields["check_in_time"]
            del self.fields["check_out_time"]


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
            if not self.instance.tax_id:
                raise forms.ValidationError(_("Enter the NIPT in Business details first."))
            for f in ("fiscal_business_unit", "fiscal_tcr_code", "fiscal_software_code", "fiscal_operator_code"):
                if not cleaned.get(f):
                    self.add_error(f, _("Needed to fiscalize."))
            if not data:
                self.add_error("certificate_file", _("Upload the certificate."))
        return cleaned


TABS = {
    "fiscal": FiscalSettingsForm,
    "payments": PaymentSettingsForm,
    "business": BusinessForm,
    "receipts": ReceiptForm,
    "modules": ModulesForm,
    "booking": BookingSettingsForm,
    "email": EmailSettingsForm,
}


@module_required("management")
def settings_hub(request):
    tab = request.GET.get("tab", "business")
    hs = HotelSettings.load()
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
        if tab == "booking":
            from django.urls import reverse

            from apps.outlets.menu import public_link

            ctx["booking_link"] = public_link(request, reverse("booking:search"))
    elif tab == "import":
        from . import importer

        ctx["import_kinds"] = [(k, v["label"], v["columns"], v["required"]) for k, v in importer.KINDS.items()]
    elif tab == "backup":
        ctx["disk_backups"] = backup.disk_backups()
        ctx["backup_dir"] = backup.backup_dir()
    else:
        raise Http404
    return render(request, "core/settings_hub.html", ctx)


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
    """Step 1: upload (or pick a saved backup) and see what's inside. Step 2: confirm."""
    if request.method == "POST" and request.FILES.get("file"):
        raw = request.FILES["file"].read()
        try:
            doc = backup.read_file(raw)
        except backup.BackupError:
            messages.error(request, _("This file is not an InnKeeper backup."))
            return redirect("/settings/?tab=backup")
        name = f"upload-{secrets.token_hex(4)}.innkeeper"
        (backup.backup_dir() / name).write_bytes(raw)
    else:
        name = request.GET.get("file", "")
        path = backup.backup_dir() / name
        if not name or "/" in name or "\\" in name or not path.is_file():
            return redirect("/settings/?tab=backup")
        try:
            doc = backup.read_file(path.read_bytes())
        except backup.BackupError:
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
        if name.startswith("upload-"):
            path.unlink(missing_ok=True)
        return redirect("/settings/?tab=backup")

    if request.POST.get("confirm_text", "").strip().upper() not in {"RESTORE", "RIKTHE"}:
        messages.error(request, _("Type RESTORE to confirm."))
        return redirect(f"/settings/restore/?file={name}")
    safety = backup.save_backup_to_disk("before-restore", keep=10)
    backup.restore_full(doc)
    if name.startswith("upload-"):
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


# ---------- Import from Excel (CSV) ----------


@module_required("management")
def import_template(request, kind):
    from . import importer

    if kind not in importer.KINDS:
        raise Http404
    response = HttpResponse("\ufeff" + importer.template_csv(kind), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="innkeeper-{kind}.csv"'
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
    if raw[:2] == b"PK":
        messages.error(
            request, _("This is an Excel file. In Excel choose File → Save as → “CSV UTF-8”, then upload that.")
        )
        return redirect("/settings/?tab=import")
    parsed = importer.parse(kind, raw)
    name = f"import-{secrets.token_hex(6)}.csv"
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
