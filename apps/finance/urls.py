from django.urls import path

from . import reports, views

app_name = "finance"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("ledger/", views.ledger, name="ledger"),
    path("day-close/", reports.day_close, name="day_close"),
    path("sales/", reports.sales, name="sales"),
    path("expenses/", reports.expense_list, name="expenses"),
    path("expenses/new/", reports.expense_form, name="expense_create"),
    path("expenses/<int:pk>/", reports.expense_form, name="expense_edit"),
    path("expenses/<int:pk>/void/", reports.expense_void, name="expense_void"),
]
