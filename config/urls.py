from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "InnKeeper"
admin.site.site_title = "InnKeeper"
admin.site.index_title = "Administration"

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("front-desk/", include("apps.frontdesk.urls")),
    path("housekeeping/", include("apps.housekeeping.urls")),
    path("outlets/", include("apps.outlets.urls")),
    path("finance/", include("apps.finance.urls")),
    path("menu/", include("apps.outlets.menu_urls")),
    path("book/", include("apps.frontdesk.booking_urls")),
    path("", include("apps.core.urls")),
]
