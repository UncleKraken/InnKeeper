"""
Small generic list / create / edit views used by the management screens
(rooms, room types, outlets, menus, tables…), so every catalogue page looks
and behaves the same.
"""

from django.contrib import messages
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import CreateView, ListView, UpdateView

from apps.accounts.permissions import ModuleRequiredMixin

from .models import audit


class CrudMixin(ModuleRequiredMixin):
    module = "management"
    title = ""
    singular = ""
    list_url_name = ""
    create_url_name = ""
    update_url_name = ""
    tabs: list[tuple[str, str]] = []  # (url name, label)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            title=self.title,
            singular=self.singular,
            list_url=reverse(self.list_url_name),
            create_url=reverse(self.create_url_name) if self.create_url_name else None,
            tabs=[(reverse(name), label, name == self.list_url_name) for name, label in self.tabs],
        )
        return ctx


class CrudListView(CrudMixin, ListView):
    template_name = "core/crud_list.html"
    paginate_by = 50
    # (attribute, label, kind) where kind is text | money | bool | choice | badge
    columns: list[tuple[str, str, str]] = []
    search_fields: list[str] = []
    # Extra buttons per row: (label, url name, icon, attribute that must be truthy or "")
    row_actions: list[tuple[str, str, str, str]] = []

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q", "").strip()
        if q and self.search_fields:
            cond = Q()
            for f in self.search_fields:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)
        return qs

    def cell(self, obj, attr, kind):
        if kind == "choice":
            return getattr(obj, f"get_{attr}_display")()
        value = obj
        for part in attr.split("."):
            value = getattr(value, part, None)
            if callable(value):
                value = value()
        return value

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["columns"] = self.columns
        ctx["rows"] = [
            (
                obj,
                reverse(self.update_url_name, args=[obj.pk]),
                [(self.cell(obj, a, k), k) for a, _l, k in self.columns],
                [
                    (label, reverse(url_name, args=[obj.pk]), icon)
                    for label, url_name, icon, cond in self.row_actions
                    if not cond or getattr(obj, cond)
                ],
            )
            for obj in ctx["object_list"]
        ]
        ctx["searchable"] = bool(self.search_fields)
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class _CrudFormMixin(CrudMixin):
    template_name = "core/crud_form.html"

    def get_success_url(self):
        return reverse(self.list_url_name)

    def form_valid(self, form):
        response = super().form_valid(form)
        audit(self.request.user, f"{self.model._meta.model_name}.save", str(self.object), self.object)
        messages.success(self.request, _("Saved %(obj)s.") % {"obj": self.object})
        return response


class CrudCreateView(_CrudFormMixin, CreateView):
    pass


class CrudUpdateView(_CrudFormMixin, UpdateView):
    pass
