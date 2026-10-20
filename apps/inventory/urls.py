from django.urls import path

from . import profit, purchasing, transfer_views, views

app_name = "inventory"

urlpatterns = [
    path("", views.stock, name="stock"),
    path("items/new/", views.StockItemCreate.as_view(), name="item_create"),
    path("items/<int:pk>/", views.item_detail, name="item_detail"),
    path("items/<int:pk>/edit/", views.StockItemEdit.as_view(), name="item_edit"),
    path("deliveries/", views.delivery_list, name="delivery_list"),
    path("deliveries/new/", views.delivery_create, name="delivery_create"),
    path("deliveries/<int:pk>/", views.delivery_detail, name="delivery_detail"),
    path("counts/", views.count_list, name="count_list"),
    path("counts/new/", views.count_create, name="count_create"),
    path("counts/<int:pk>/", views.count_detail, name="count_detail"),
    path("recipes/", views.recipes, name="recipes"),
    path("recipes/<int:item_id>/", views.recipe_edit, name="recipe_edit"),
    path("recipes/<int:item_id>/track/", views.recipe_track, name="recipe_track"),
    path("usage/", views.usage, name="usage"),
    path("menu-profit/", profit.menu_profit, name="menu_profit"),
    path("orders/", purchasing.order_list, name="order_list"),
    path("orders/new/", purchasing.order_create, name="order_create"),
    path("orders/low-stock/", purchasing.order_from_low_stock, name="order_low_stock"),
    path("orders/<int:pk>/", purchasing.order_detail, name="order_detail"),
    path("orders/<int:pk>/print/", purchasing.order_print, name="order_print"),
    path("orders/<int:pk>/<str:action>/", purchasing.order_action, name="order_action"),
    path("transfers/", transfer_views.transfer_list, name="transfers"),
    path("transfers/send/", transfer_views.transfer_send, name="transfer_send"),
    path("transfers/receive/", transfer_views.transfer_receive, name="transfer_receive"),
    path("transfers/<int:pk>/", transfer_views.transfer_detail, name="transfer_detail"),
    path("suppliers/", views.SupplierList.as_view(), name="supplier_list"),
    path("suppliers/new/", views.SupplierCreate.as_view(), name="supplier_create"),
    path("suppliers/<int:pk>/", views.SupplierEdit.as_view(), name="supplier_edit"),
]
