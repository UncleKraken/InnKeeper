from django.urls import path

from . import views

app_name = "housekeeping"

urlpatterns = [
    path("board/", views.board, name="board"),
    path("rooms/<int:pk>/status/", views.room_status, name="room_status"),
    path("tasks/new/", views.task_create, name="task_create"),
    path("tasks/<int:pk>/advance/", views.task_advance, name="task_advance"),
    path("tasks/<int:pk>/assign/", views.task_assign, name="task_assign"),
    path("maintenance/", views.ticket_list, name="ticket_list"),
    path("maintenance/new/", views.ticket_form, name="ticket_create"),
    path("maintenance/<int:pk>/", views.ticket_form, name="ticket_edit"),
    path("maintenance/<int:pk>/status/", views.ticket_status, name="ticket_status"),
]
