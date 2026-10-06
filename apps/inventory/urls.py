from django.urls import path

from . import views

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
    path("suppliers/", views.SupplierList.as_view(), name="supplier_list"),
    path("suppliers/new/", views.SupplierCreate.as_view(), name="supplier_create"),
    path("suppliers/<int:pk>/", views.SupplierEdit.as_view(), name="supplier_edit"),
]
