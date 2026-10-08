from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

from apps.frontdesk.channel_manager import channex_webhook
from apps.frontdesk.channels import room_calendar

admin.site.site_header = "InnKeeper"
admin.site.site_title = "InnKeeper"
admin.site.index_title = "Administration"


def admin_login(request):
    """The admin uses InnKeeper's own sign-in, which locks out after repeated wrong passwords."""
    from django.urls import reverse

    query = request.META.get("QUERY_STRING", "")
    return redirect(reverse("accounts:login") + (f"?{query}" if query else ""))


urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/login/", admin_login),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("front-desk/", include("apps.frontdesk.urls")),
    path("housekeeping/", include("apps.housekeeping.urls")),
    path("outlets/", include("apps.outlets.urls")),
    path("finance/", include("apps.finance.urls")),
    path("stock/", include("apps.inventory.urls")),
    path("fiscal/", include("apps.fiscal.urls")),
    path("menu/", include("apps.outlets.menu_urls")),
    path("book/", include("apps.frontdesk.booking_urls")),
    path("pay/", include("apps.payments.urls")),
    path("ical/<str:token>.ics", room_calendar, name="ical_room"),
    path("channex/webhook/<str:token>/", channex_webhook, name="channex_webhook"),
    path("", include("apps.core.urls")),
]
