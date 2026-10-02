from django.urls import path

from . import views

app_name = "outlets"

urlpatterns = [
    path("", views.home, name="home"),
    path("<int:pk>/", views.floor, name="floor"),
    path("<int:pk>/table/<int:table_id>/", views.open_table, name="open_table"),
    path("<int:pk>/new-order/", views.new_order, name="new_order"),
    path("orders/<int:pk>/", views.order_view, name="order"),
    path("orders/<int:pk>/add/", views.add_item, name="add_item"),
    path("orders/<int:pk>/line/<int:line_id>/", views.change_line, name="change_line"),
    path("orders/<int:pk>/update/", views.update_order, name="update_order"),
    path("orders/<int:pk>/settle/", views.settle, name="settle"),
    path("orders/<int:pk>/cancel/", views.cancel, name="cancel"),
    path("orders/<int:pk>/receipt/", views.receipt, name="receipt"),
    path("setup/", views.OutletList.as_view(), name="setup"),
    path("setup/outlets/new/", views.OutletCreate.as_view(), name="outlet_create"),
    path("setup/outlets/<int:pk>/", views.OutletEdit.as_view(), name="outlet_edit"),
    path("setup/categories/", views.CategoryList.as_view(), name="category_list"),
    path("setup/categories/new/", views.CategoryCreate.as_view(), name="category_create"),
    path("setup/categories/<int:pk>/", views.CategoryEdit.as_view(), name="category_edit"),
    path("setup/items/", views.ItemList.as_view(), name="item_list"),
    path("setup/items/new/", views.ItemCreate.as_view(), name="item_create"),
    path("setup/items/<int:pk>/", views.ItemEdit.as_view(), name="item_edit"),
    path("setup/tables/", views.TableList.as_view(), name="table_list"),
    path("setup/tables/new/", views.TableCreate.as_view(), name="table_create"),
    path("setup/tables/<int:pk>/", views.TableEdit.as_view(), name="table_edit"),
]
