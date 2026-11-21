import unittest

from telegram_action import format_premarket_message


class PreMarketTelegramFormattingTests(unittest.TestCase):
    def test_report_uses_real_line_breaks_not_literal_escape_sequences(self):
        message = format_premarket_message({
            "direction": "BEARISH BIAS",
            "confidence": 65,
            "checked_at": "2026-11-21T09:00+05:30",
            "session_time_ist": "09:00",
            "india_vix": 17.32,
            "volatility": "ELEVATED",
            "risk_note": "VIX is elevated.",
            "rows": [
                {"indicator": "DOW", "change_pct": -1.93, "status": "negative"},
                {"indicator": "GIFT NIFTY IMPLIED GAP", "change_pct": None, "status": "unavailable"},
            ],
        })
        self.assertIn("\n", message)
        self.assertNotIn("\\n", message)
        self.assertIn("\n🔴", message)
        self.assertIn("\n<b>GLOBAL / OVERNIGHT INPUTS</b>\n", message)

    def test_after_hours_report_is_not_mislabeled_as_pre_market_forecast(self):
        message = format_premarket_message({
            "direction": "BEARISH BIAS",
            "confidence": 65,
            "checked_at": "2026-11-21T17:38+05:30",
            "session_time_ist": "17:38",
            "rows": [],
        })
        self.assertIn("MARKET CONTEXT SNAPSHOT", message)
        self.assertNotIn("PRE-MARKET OUTLOOK", message)
        self.assertIn("Outside the 08:30–09:15 IST pre-market window", message)


if __name__ == "__main__":
    unittest.main()
