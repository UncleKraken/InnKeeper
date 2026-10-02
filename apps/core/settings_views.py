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
        fields = ["business_type", "module_rooms", "module_housekeeping", "module_maintenance", "module_outlets"]
        widgets = {"business_type": forms.RadioSelect}

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(f) for f in ("module_rooms", "module_maintenance", "module_outlets")):
            raise forms.ValidationError(_("Switch on at least one area."))
        return cleaned


TABS = {"business": BusinessForm, "receipts": ReceiptForm, "modules": ModulesForm}


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
