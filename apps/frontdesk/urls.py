from django.urls import path

from . import views

app_name = "frontdesk"

urlpatterns = [
    path("rack/", views.rack, name="rack"),
    path("reservations/", views.reservation_list, name="reservation_list"),
    path("reservations/new/", views.reservation_form, name="reservation_create"),
    path("reservations/<int:pk>/", views.reservation_detail, name="reservation_detail"),
    path("reservations/<int:pk>/edit/", views.reservation_form, name="reservation_edit"),
    path("reservations/<int:pk>/check-in/", views.check_in, name="check_in"),
    path("reservations/<int:pk>/check-out/", views.check_out, name="check_out"),
    path("reservations/<int:pk>/cancel/", views.cancel, name="cancel"),
    path("reservations/<int:pk>/charge/", views.add_charge, name="add_charge"),
    path("reservations/<int:pk>/payment/", views.add_payment, name="add_payment"),
    path("reservations/<int:pk>/void/<str:kind>/<int:entry_id>/", views.void_entry, name="void_entry"),
    path("reservations/<int:pk>/invoice/", views.invoice, name="invoice"),
    path("guests/", views.guest_list, name="guest_list"),
    path("guests/new/", views.guest_form, name="guest_create"),
    path("guests/<int:pk>/", views.guest_detail, name="guest_detail"),
    path("guests/<int:pk>/edit/", views.guest_form, name="guest_edit"),
    path("setup/rooms/", views.RoomList.as_view(), name="room_list"),
    path("setup/rooms/new/", views.RoomCreate.as_view(), name="room_create"),
    path("setup/rooms/<int:pk>/", views.RoomEdit.as_view(), name="room_edit"),
    path("setup/room-types/", views.RoomTypeList.as_view(), name="roomtype_list"),
    path("setup/room-types/new/", views.RoomTypeCreate.as_view(), name="roomtype_create"),
    path("setup/room-types/<int:pk>/", views.RoomTypeEdit.as_view(), name="roomtype_edit"),
]
