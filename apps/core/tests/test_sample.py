from django.urls import reverse

from apps.accounts.models import Role, User
from apps.core import sample
from apps.core.models import HotelSettings, clear_settings_cache
from apps.frontdesk.models import Reservation, Room
from apps.outlets.models import Order
from django.test import TestCase

PASSWORD = "a-strong-test-pass-91"


class SampleDataTests(TestCase):
    def setUp(self):
        clear_settings_cache()
        self.owner = User.objects.create_user("owner", password=PASSWORD, role=Role.MANAGER)
        self.client.login(username="owner", password=PASSWORD)

    def test_offered_on_an_empty_system_then_removed(self):
        page = self.client.get(reverse("core:setup"))
        self.assertTrue(page.context["can_sample"])
        r = self.client.post(reverse("core:sample_load"))
        self.assertRedirects(r, reverse("core:dashboard"), fetch_redirect_response=False)
        clear_settings_cache()
        hs = HotelSettings.load()
        self.assertTrue(hs.demo_data and hs.setup_completed)
        self.assertFalse(hs.fiscal_enabled)
        self.assertTrue(Room.objects.exists() and Order.objects.exists())
        self.assertFalse(User.objects.get(username="sample.waiter").has_usable_password())
        self.assertContains(self.client.get(reverse("core:dashboard")), reverse("core:sample_remove"))
        # every main screen works with it
        for name in ("frontdesk:rack", "outlets:home", "core:dashboard", "finance:dashboard", "inventory:stock", "inventory:order_list", "finance:sales"):
            url = reverse(name)
            self.assertEqual(self.client.get(url).status_code, 200, name)

        self.client.post(reverse("core:sample_remove"), {})  # not confirmed
        self.assertTrue(Room.objects.exists())
        r = self.client.post(reverse("core:sample_remove"), {"confirm": "1"})
        self.assertRedirects(r, reverse("core:setup"), fetch_redirect_response=False)
        self.assertFalse(Room.objects.exists() or Reservation.objects.exists() or Order.objects.exists())
        self.assertEqual(list(User.objects.values_list("username", flat=True)), ["owner"])
        clear_settings_cache()
        self.assertFalse(HotelSettings.load().demo_data or HotelSettings.load().setup_completed)
        self.assertEqual(self.client.get(reverse("core:setup")).status_code, 200)  # still signed in

    def test_not_offered_and_not_removable_on_a_real_business(self):
        HotelSettings.objects.update_or_create(pk=1, defaults={"setup_completed": True})
        clear_settings_cache()
        from apps.frontdesk.models import RoomType

        Room.objects.create(number="1", room_type=RoomType.objects.create(name="D", code="D", base_rate=1))
        self.assertFalse(sample.is_empty())
        self.client.post(reverse("core:sample_load"))
        self.client.post(reverse("core:sample_remove"), {"confirm": "1"})
        self.assertTrue(Room.objects.exists())
        self.assertFalse(HotelSettings.objects.get().demo_data)
