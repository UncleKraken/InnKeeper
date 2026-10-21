from django.contrib.auth import views as auth_views
from django.urls import path

from . import pin, twofactor, views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("welcome/", views.first_run, name="first_run"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("language/", views.set_language, name="set_language"),
    path("password/", views.password_change, name="password_change"),
    path("staff/", views.StaffList.as_view(), name="staff_list"),
    path("staff/new/", views.StaffCreate.as_view(), name="staff_create"),
    path("staff/<int:pk>/", views.StaffEdit.as_view(), name="staff_edit"),
    path("staff/<int:pk>/password/", views.staff_set_password, name="staff_set_password"),
    path("staff/<int:pk>/pin/", pin.staff_set_pin, name="staff_set_pin"),
    path("my-pin/", pin.my_pin, name="my_pin"),
    path("pin/", pin.pin_pad, name="pin_pad"),
    path("lock/", pin.lock, name="lock"),
    path("shared-till/", pin.shared_till, name="shared_till"),
    path("two-step/", twofactor.manage, name="two_step"),
    path("two-step/verify/", twofactor.verify, name="two_step_verify"),
    path("two-step/off/", twofactor.disable, name="two_step_off"),
    path("two-step/recovery/", twofactor.new_recovery_codes, name="two_step_recovery"),
    path("staff/<int:pk>/two-step/off/", twofactor.staff_reset, name="staff_two_step_off"),
]
