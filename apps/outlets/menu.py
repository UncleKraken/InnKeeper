"""Guest-facing menus: a public page per outlet, a printable menu and QR codes."""

import io

import qrcode
import qrcode.image.svg
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import translation
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_enabled, module_required

from .models import Item, Outlet


def qr_svg(url: str) -> str:
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    return mark_safe(svg[svg.index("<svg") :])


def public_link(request, path: str) -> str:
    """Full link for guests: the public address from Settings if set, else the address in use now."""
    from apps.core.models import HotelSettings

    base = HotelSettings.load().public_url
    return (base.rstrip("/") + path) if base else request.build_absolute_uri(path)


def _menu_sections(outlet: Outlet, lang: str):
    english = lang == "en"
    sections = []
    for cat in outlet.categories.prefetch_related("items"):
        items = [
            {
                "name": (i.name_en if english and i.name_en else i.name),
                "description": (i.description_en if english and i.description_en else i.description),
                "price": i.price,
                "duration": i.duration_minutes,
            }
            for i in cat.items.all()
            if i.is_active
        ]
        if items:
            sections.append({"name": cat.name_en if english and cat.name_en else cat.name, "items": items})
    return sections


def public_menu(request, token, printable=False):
    outlet = get_object_or_404(Outlet, menu_token=token, is_active=True)
    if not outlet.menu_public or not module_enabled("outlets"):
        raise Http404
    lang = request.GET.get("lang") or translation.get_language() or "sq"
    lang = "en" if lang.startswith("en") else "sq"
    translation.activate(lang)
    return render(
        request,
        "outlets/menu_print.html" if printable else "outlets/menu_public.html",
        {"outlet": outlet, "sections": _menu_sections(outlet, lang), "lang": lang},
    )


def public_menu_print(request, token):
    return public_menu(request, token, printable=True)


@module_required("management")
def menu_admin(request, pk):
    outlet = get_object_or_404(Outlet, pk=pk)
    url = public_link(request, reverse("menu:public", args=[outlet.menu_token]))
    host = url.split("//", 1)[-1].split("/")[0].split(":")[0]
    return render(
        request,
        "outlets/menu_admin.html",
        {
            "outlet": outlet,
            "url": url,
            "qr": qr_svg(url),
            "local_only": host in {"localhost", "127.0.0.1", "0.0.0.0"},
            "categories": outlet.categories.prefetch_related("items"),
        },
    )


@module_required("management")
def menu_qr_cards(request, pk):
    outlet = get_object_or_404(Outlet, pk=pk)
    url = public_link(request, reverse("menu:public", args=[outlet.menu_token]))
    return render(request, "outlets/menu_qr_cards.html", {"outlet": outlet, "qr": qr_svg(url), "cards": range(8)})


@require_POST
@module_required("outlets")
def toggle_item(request, pk):
    """Mark an item sold out / available again (managers, from the menu page)."""
    if not request.user.is_manager:
        raise Http404
    item = get_object_or_404(Item, pk=pk)
    item.is_active = not item.is_active
    item.save(update_fields=["is_active"])
    messages.success(
        request,
        (_("%(item)s is available again.") if item.is_active else _("%(item)s is marked as sold out."))
        % {"item": item.name},
    )
    return redirect(request.POST.get("next") or reverse("outlets:menu_admin", args=[item.category.outlet_id]))


@require_POST
@module_required("management")
def new_menu_link(request, pk):
    """Make a new QR link (e.g. after printing the wrong one). Old printed codes stop working."""
    outlet = get_object_or_404(Outlet, pk=pk)
    outlet.menu_token = ""
    outlet.save()
    messages.success(request, _("New menu link created. Print the new QR code."))
    return redirect("outlets:menu_admin", pk=pk)
