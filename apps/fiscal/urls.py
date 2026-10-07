from django.urls import path

from . import views

app_name = "fiscal"

urlpatterns = [
    path("", views.documents, name="documents"),
    path("resend/", views.resend, name="resend_all"),
    path("<int:pk>/resend/", views.resend, name="resend"),
    path("cash/", views.cash, name="cash"),
]
