from django.urls import path

from . import views

app_name = "news"

urlpatterns = [
    path("", views.signup, name="signup"),
    path("unsubscribe/<str:token>/", views.unsubscribe, name="unsubscribe"),
]
