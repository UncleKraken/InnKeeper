from datetime import timedelta
from decimal import Decimal as D

from apps.core.models import HotelSettings, clear_settings_cache
from apps.core.testing import HotelTestCase
from apps.finance.models import DayClose
from apps.fiscal.services import opening_cash
from apps.outlets.models import Outlet


class OpeningCashTests(HotelTestCase):
    def setUp(self):
        HotelSettings.objects.update(fiscal_tcr_code="main0000aa")
        clear_settings_cache()
        DayClose.objects.create(
            business_date=self.today - timedelta(days=1), opening_float=0, cash_sales=0, cash_expenses=0,
            expected_cash=D("300"), counted_cash=D("300"),
        )

    def test_single_register_reports_the_counted_cash(self):
        self.assertEqual(opening_cash("main0000aa", self.today), D("300"))

    def test_each_register_its_own_float_and_main_the_rest(self):
        Outlet.objects.create(name="Beach bar", kind="bar", fiscal_tcr_code="beach0000a", fiscal_opening_cash=D("50"))
        Outlet.objects.create(name="Club", kind="bar", fiscal_tcr_code="club00000a", fiscal_opening_cash=D("80"))
        self.assertEqual(opening_cash("beach0000a", self.today), D("50"))
        self.assertEqual(opening_cash("club00000a", self.today), D("80"))
        self.assertEqual(opening_cash("main0000aa", self.today), D("170"))
        self.assertEqual(opening_cash("unknown000", self.today), D("0"))
