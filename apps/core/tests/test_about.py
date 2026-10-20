from django.urls import reverse

from apps.core.models import HotelSettings
from apps.core.testing import PASSWORD, HotelTestCase


class AboutTests(HotelTestCase):
    def test_about_page_with_share_links(self):
        self.client.login(username="waiter", password=PASSWORD)
        r = self.client.get(reverse("core:about"))
        self.assertContains(r, "wa.me/?text=")
        self.assertContains(r, "unclekraken.github.io/InnKeeper")
        self.assertContains(r, "<svg")

    def test_made_with_link_on_public_pages_can_be_turned_off(self):
        self.restaurant.menu_public = True
        self.restaurant.save()
        url = reverse("menu:public", args=[self.restaurant.menu_token])
        self.assertContains(self.client.get(url), "made-with")
        hs = HotelSettings.load()
        hs.show_made_with = False
        hs.save()
        self.assertNotContains(self.client.get(url), "made-with")
