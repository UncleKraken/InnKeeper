from django.urls import path

from . import views

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
    path("positions/", views.PositionList.as_view(), name="position_list"),
    path("positions/new/", views.PositionCreate.as_view(), name="position_create"),
    path("positions/<int:pk>/", views.PositionEdit.as_view(), name="position_edit"),
]
