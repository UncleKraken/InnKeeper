from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.crud import CrudCreateView, CrudListView, CrudUpdateView
from apps.core.forms import StyledFormMixin
from apps.core.models import audit

from .forms import LoginForm, SetPasswordStaffForm, StaffCreateForm, StaffForm
from .models import User
from .permissions import module_required


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if not User.objects.exists():
            return redirect("accounts:first_run")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        audit(self.request.user, "auth.login", str(self.request.user))
        return response


@require_POST
def set_language(request):
    lang = request.POST.get("language", "")
    nxt = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        nxt = "/"
    response = redirect(nxt)
    if lang in {"sq", "en"}:
        translation.activate(lang)
        response.set_cookie("django_language", lang, max_age=365 * 24 * 3600, samesite="Lax")
        if request.user.is_authenticated:
            request.user.language = lang
            request.user.save(update_fields=["language"])
    return response


class StyledPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    pass


@login_required
def password_change(request):
    form = StyledPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        audit(user, "auth.password_change", str(user), user)
        messages.success(request, _("Your password was changed."))
        return redirect("core:dashboard")
    return render(request, "accounts/password_change.html", {"form": form})


# ---------- Staff management (managers) ----------


class StaffList(CrudListView):
    model = User
    title = _("Staff")
    singular = _("staff member")
    list_url_name = "accounts:staff_list"
    create_url_name = "accounts:staff_create"
    update_url_name = "accounts:staff_edit"
    search_fields = ["username", "first_name", "last_name", "email"]
    columns = [
        ("__str__", _("Name"), "text"),
        ("username", _("Username"), "text"),
        ("role", _("Role"), "choice"),
        ("phone", _("Phone"), "text"),
        ("last_login", _("Last sign-in"), "text"),
        ("is_active", _("Active"), "bool"),
    ]


class StaffCreate(CrudCreateView):
    model = User
    form_class = StaffCreateForm
    title = _("Staff")
    singular = _("staff member")
    list_url_name = "accounts:staff_list"


class StaffEdit(CrudUpdateView):
    model = User
    form_class = StaffForm
    title = _("Staff")
    singular = _("staff member")
    list_url_name = "accounts:staff_list"
    template_name = "accounts/staff_form.html"

    def form_valid(self, form):
        if form.instance.pk == self.request.user.pk and not form.cleaned_data["is_active"]:
            form.add_error("is_active", _("You cannot deactivate your own account."))
            return self.form_invalid(form)
        return super().form_valid(form)


@module_required("management")
def staff_set_password(request, pk):
    staff = get_object_or_404(User, pk=pk)
    form = SetPasswordStaffForm(staff, request.POST or None)
    if request.method == "POST" and form.is_valid():
        staff.set_password(form.cleaned_data["password1"])
        staff.save(update_fields=["password"])
        audit(request.user, "staff.set_password", str(staff), staff)
        messages.success(
            request, _("New password set for %(name)s. Tell them in person, not by message.") % {"name": staff}
        )
        return redirect("accounts:staff_edit", pk=staff.pk)
    return render(
        request,
        "core/crud_form.html",
        {
            "form": form,
            "object": staff,
            "title": _("Set password"),
            "list_url": reverse("accounts:staff_edit", args=[pk]),
        },
    )


def first_run(request):
    """Create the very first manager account on a brand-new installation."""
    from django.contrib.auth import login

    from .forms import FirstRunForm
    from .models import Role

    if User.objects.exists():
        return redirect("accounts:login")
    form = FirstRunForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        user = User.objects.create_user(
            d["username"],
            password=d["password1"],
            first_name=d["first_name"],
            last_name=d["last_name"],
            role=Role.MANAGER,
            is_staff=True,
            is_superuser=True,
        )
        login(request, user)
        audit(user, "auth.first_run", str(user), user)
        return redirect("core:setup")
    return render(request, "accounts/first_run.html", {"form": form})
