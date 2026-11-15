import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from radar.market_clock import get_market_status, format_market_status

IST = ZoneInfo("Asia/Kolkata")


class MarketClockTests(unittest.TestCase):
    def test_regular_session_opens_at_0915(self):
        status = get_market_status(datetime(2026, 11, 16, 9, 15, tzinfo=IST))
        self.assertEqual(status["phase"], "open")
        self.assertTrue(status["regular_open"])
        self.assertTrue(status["calendar_verified"])

    def test_preopen_is_not_regular_market_open(self):
        status = get_market_status(datetime(2026, 11, 16, 9, 14, tzinfo=IST))
        self.assertEqual(status["phase"], "pre_open")
        self.assertFalse(status["regular_open"])

    def test_post_close_is_not_open(self):
        status = get_market_status(datetime(2026, 11, 16, 15, 31, tzinfo=IST))
        self.assertEqual(status["phase"], "post_market")
        self.assertFalse(status["regular_open"])

    def test_sunday_is_weekend_and_next_open_is_monday(self):
        status = get_market_status(datetime(2026, 11, 15, 10, 0, tzinfo=IST))
        self.assertEqual(status["phase"], "weekend")
        self.assertEqual(status["next_open"], "2026-11-16T09:15+05:30")

    def test_nse_holiday_is_closed(self):
        status = get_market_status(datetime(2026, 11, 24, 10, 0, tzinfo=IST))
        self.assertEqual(status["phase"], "holiday")
        self.assertFalse(status["regular_open"])
        self.assertIn("Guru Nanak", status["reason"])

    def test_muhurat_preopen_uses_special_session_time(self):
        status = get_market_status(datetime(2026, 11, 8, 14, 10, tzinfo=IST))
        self.assertEqual(status["phase"], "pre_open")
        self.assertEqual(status["session_type"], "special")
        self.assertIn("14:20", status["reason"])

    def test_muhurat_equity_cash_session_is_open(self):
        status = get_market_status(datetime(2026, 11, 8, 14, 25, tzinfo=IST))
        self.assertEqual(status["phase"], "open")
        self.assertTrue(status["regular_open"])
        self.assertEqual(status["session_name"], "Diwali Muhurat Trading")

    def test_muhurat_equity_cash_session_closes_at_1530(self):
        status = get_market_status(datetime(2026, 11, 8, 15, 31, tzinfo=IST))
        self.assertEqual(status["phase"], "post_market")
        self.assertFalse(status["regular_open"])

    def test_next_session_from_muhurat_preopen_is_special_open_time(self):
        status = get_market_status(datetime(2026, 11, 8, 14, 10, tzinfo=IST))
        self.assertEqual(status["next_open"], "2026-11-08T14:20+05:30")

    def test_unknown_year_fails_closed(self):
        status = get_market_status(datetime(2027, 1, 4, 10, 0, tzinfo=IST))
        self.assertEqual(status["phase"], "calendar_unverified")
        self.assertFalse(status["regular_open"])

    def test_closed_message_says_no_recommendations(self):
        status = get_market_status(datetime(2026, 11, 15, 10, 0, tzinfo=IST))
        message = format_market_status(status)
        self.assertIn("WEEKEND", message)
        self.assertIn("No live stock recommendations", message)


if __name__ == "__main__":
    unittest.main()
