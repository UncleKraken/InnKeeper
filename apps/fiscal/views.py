from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import module_required
from apps.core.models import HotelSettings

from . import services
from .models import CashDeposit, FiscalDocument
from .signing import CertificateError


def fiscal_block(doc: FiscalDocument | None) -> dict:
    """Context for templates/fiscal/_block.html (receipts and invoices)."""
    if doc is None:
        return {"fdoc": None, "qr": ""}
    from apps.outlets.menu import qr_svg

    return {"fdoc": doc, "qr": qr_svg(doc.verify_url)}


@module_required("finance")
def documents(request):
    status = request.GET.get("status", "")
    qs = FiscalDocument.objects.select_related("order__outlet", "folio__reservation__guest")
    if status:
        qs = qs.filter(status=status)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    hs = HotelSettings.load()
    from apps.outlets.models import Outlet

    tcrs = sorted(
        {
            t
            for t in [
                hs.fiscal_tcr_code,
                *Outlet.objects.exclude(fiscal_tcr_code="").values_list("fiscal_tcr_code", flat=True),
            ]
            if t
        }
    )
    return render(
        request,
        "fiscal/documents.html",
        {
            "page_obj": page,
            "status": status,
            "statuses": FiscalDocument.Status.choices,
            "waiting": FiscalDocument.objects.filter(status=FiscalDocument.Status.PENDING).count(),
            "failed": FiscalDocument.objects.filter(status=FiscalDocument.Status.FAILED).count(),
            "deposits": CashDeposit.objects.all()[:10],
            "tcrs": tcrs,
        },
    )


@require_POST
@module_required("finance")
def resend(request, pk=None):
    if pk:
        doc = get_object_or_404(FiscalDocument, pk=pk)
        if doc.status == FiscalDocument.Status.FAILED:
            doc.status = FiscalDocument.Status.PENDING
            doc.save(update_fields=["status"])
        services.transmit(doc)
        if doc.status == FiscalDocument.Status.REGISTERED:
            messages.success(request, _("Registered: NIVF %(fic)s") % {"fic": doc.fic})
        else:
            messages.error(request, doc.last_error)
    else:
        n = services.resend_pending()
        messages.success(request, _("%(n)s document(s) registered.") % {"n": n})
    return redirect("fiscal:documents")


@require_POST
@module_required("finance")
def cash(request):
    if not services.enabled():
        messages.error(request, _("Fiscalization is not set up."))
        return redirect("fiscal:documents")
    op = request.POST.get("operation")
    tcr = request.POST.get("tcr") or HotelSettings.load().fiscal_tcr_code
    try:
        amount = Decimal(request.POST.get("amount", "").replace(",", "."))
    except InvalidOperation:
        amount = Decimal("-1")
    if op not in CashDeposit.Operation.values or amount < 0:
        messages.error(request, _("Enter an amount of zero or more."))
        return redirect("fiscal:documents")
    try:
        dep = services.register_cash(tcr, op, amount, request.user)
    except CertificateError as e:
        messages.error(request, str(e))
        return redirect("fiscal:documents")
    if dep.status == "registered":
        messages.success(
            request,
            _("Reported to the tax authority: %(op)s %(a)s.") % {"op": dep.get_operation_display(), "a": dep.amount},
        )
    else:
        messages.error(request, _("Not registered: %(e)s") % {"e": dep.last_error})
    return redirect("fiscal:documents")
