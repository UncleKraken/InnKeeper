from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

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
]
