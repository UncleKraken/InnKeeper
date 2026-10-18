from django.urls import path

from . import monthly, reports, tab_views, views

app_name = "finance"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("ledger/", views.ledger, name="ledger"),
    path("day-close/", reports.day_close, name="day_close"),
    path("sales/", reports.sales, name="sales"),
    path("month/", monthly.monthly, name="monthly"),
    path("expenses/", reports.expense_list, name="expenses"),
    path("expenses/new/", reports.expense_form, name="expense_create"),
    path("expenses/<int:pk>/", reports.expense_form, name="expense_edit"),
    path("expenses/<int:pk>/void/", reports.expense_void, name="expense_void"),
    path("accounts/", tab_views.accounts, name="accounts"),
    path("accounts/new/", tab_views.account_form, name="account_create"),
    path("accounts/<int:pk>/", tab_views.account_detail, name="account"),
    path("accounts/<int:pk>/edit/", tab_views.account_form, name="account_edit"),
    path("accounts/<int:pk>/pay/", tab_views.account_pay, name="account_pay"),
    path("shift/", tab_views.my_shift, name="my_shift"),
    path("shift/start/", tab_views.shift_start, name="shift_start"),
    path("shift/<int:pk>/end/", tab_views.shift_end, name="shift_end"),
    path("shift/<int:pk>/", tab_views.shift_report, name="shift_report"),
    path("shifts/", tab_views.shifts, name="shifts"),
]
