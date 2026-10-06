from django.contrib import admin

from .models import Delivery, RecipeLine, StockCount, StockItem, StockMove, Supplier

admin.site.register([Supplier, StockItem, RecipeLine, Delivery, StockCount, StockMove])
