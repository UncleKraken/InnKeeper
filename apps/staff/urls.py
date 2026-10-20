from django.urls import path

from . import payroll_views, request_views, views

app_name = "staff"

urlpatterns = [
    path("clock/", views.clock, name="clock"),
    path("me/", views.my_hours, name="my_hours"),
    path("attendance/", views.attendance, name="attendance"),
    path("people/<int:pk>/hours/", views.person_hours, name="person_hours"),
    path("people/<int:pk>/clock/", views.clock_for, name="clock_for"),
    path("people/<int:user_pk>/hours/add/", views.entry_edit, name="entry_add"),
    path("people/<int:pk>/details/", views.profile, name="profile"),
    path("hours/<int:pk>/", views.entry_edit, name="entry_edit"),
    path("schedule/", views.schedule, name="schedule"),
    path("schedule/new/", views.shift_form, name="shift_create"),
    path("schedule/<int:pk>/", views.shift_form, name="shift_edit"),
    path("schedule/copy/", views.copy_week, name="copy_week"),
    path("requests/", request_views.requests_page, name="requests"),
    path("requests/leave/<int:pk>/", request_views.leave_decide, name="leave_decide"),
    path("requests/swap/<int:pk>/", request_views.swap_decide, name="swap_decide"),
    path("me/leave/", request_views.leave_ask, name="leave_ask"),
    path("me/leave/<int:pk>/cancel/", request_views.leave_cancel, name="leave_cancel"),
    path("me/swap/", request_views.swap_ask, name="swap_ask"),
    path("me/swap/<int:pk>/answer/", request_views.swap_answer, name="swap_answer"),
    path("me/swap/<int:pk>/cancel/", request_views.swap_cancel, name="swap_cancel"),
    path("payroll/", payroll_views.payroll_page, name="payroll"),
    path("payroll/rates/", payroll_views.rates, name="payroll_rates"),
    path("payroll/adjustment/", payroll_views.adjustment, name="payroll_adjustment"),
    path("payroll/approve/", payroll_views.approve, name="payroll_approve"),
    path("payroll/holidays/", payroll_views.holidays, name="holidays"),
    path("positions/", views.PositionList.as_view(), name="position_list"),
    path("positions/new/", views.PositionCreate.as_view(), name="position_create"),
    path("positions/<int:pk>/", views.PositionEdit.as_view(), name="position_edit"),
]
