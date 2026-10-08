from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin

from .models import User

MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 15 * 60


def _client_ip(request) -> str:
    from apps.core.middleware import client_ip

    return client_ip(request)


class LoginForm(StyledFormMixin, AuthenticationForm):
    """Standard Django login, plus a lockout after repeated wrong passwords."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": _("Wrong username or password."),
        "locked": _("Too many failed attempts. Try again in 15 minutes or ask a manager."),
    }

    def _key(self) -> str:
        username = (self.data.get("username") or "").strip().lower()
        return f"innkeeper:login-fail:{username}:{_client_ip(self.request)}"

    def clean(self):
        key = self._key()
        if cache.get(key, 0) >= MAX_FAILED_LOGINS:
            raise forms.ValidationError(self.error_messages["locked"], code="locked")
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, LOCKOUT_SECONDS)
            raise
        cache.delete(key)
        return cleaned


class StaffForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "role",
            "email",
            "phone",
            "language",
            "fiscal_operator_code",
            "is_active",
        ]
        help_texts = {"is_active": _("Inactive staff cannot sign in. Use this instead of deleting accounts.")}


class StaffCreateForm(StaffForm):
    password1 = forms.CharField(label=_("Password"), widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label=_("Repeat password"), widget=forms.PasswordInput, strip=False)

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", _("The passwords do not match."))
        elif p1:
            try:
                password_validation.validate_password(p1, self.instance)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class SetPasswordStaffForm(StyledFormMixin, forms.Form):
    password1 = forms.CharField(label=_("New password"), widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label=_("Repeat password"), widget=forms.PasswordInput, strip=False)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", _("The passwords do not match."))
        elif p1:
            try:
                password_validation.validate_password(p1, self.user)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return cleaned


class FirstRunForm(StyledFormMixin, forms.Form):
    first_name = forms.CharField(label=_("Your first name"), max_length=150)
    last_name = forms.CharField(label=_("Your last name"), max_length=150, required=False)
    username = forms.CharField(
        label=_("Username"), max_length=150, help_text=_("What you'll type to sign in, e.g. arta.")
    )
    password1 = forms.CharField(label=_("Password"), widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label=_("Repeat password"), widget=forms.PasswordInput, strip=False)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        User.username_validator(username)
        return username

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", _("The passwords do not match."))
        elif p1:
            try:
                password_validation.validate_password(p1, User(username=cleaned.get("username", "")))
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return cleaned
