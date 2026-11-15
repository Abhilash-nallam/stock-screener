import unittest
import pandas as pd

from telegram_bot import _pct, _risk, _stock_card, format_scan_messages


class TelegramFormattingTests(unittest.TestCase):
    def test_positive_and_negative_moves_have_coloured_indicators(self):
        self.assertIn("🟢", _pct(2.5))
        self.assertIn("🔴", _pct(-1.2))
        self.assertIn("⚪", _pct(0))

    def test_risk_colours_are_clear(self):
        self.assertIn("🔴", _risk("High"))
        self.assertIn("🟡", _risk("Moderate"))
        self.assertIn("🟢", _risk("Controlled"))

    def test_stock_card_has_clear_labels_and_real_line_breaks(self):
        row = {
            "symbol": "TEST", "company": "Test Limited", "exchange": "NSE", "score": 82.5,
            "price": 123.45, "change_1d_pct": -1.2, "ret5_pct": 2.2, "ret20_pct": -1.1,
            "entry_low": 121, "entry_high": 124, "stop_loss": 115,
            "target1": 140, "target2": 150, "risk": "Moderate",
            "rsi": 61, "rvol": 1.8, "setup_status": "Watchlist candidate",
            "reasons": ["Trend positive", "Relative strength positive"],
        }
        card = _stock_card(row, 1)
        for text in ("TEST", "Test Limited", "Last close", "Model rank", "Entry reference",
                     "Stop reference", "Targets", "RSI", "Why ranked", "Watchlist candidate"):
            self.assertIn(text, card)
        self.assertIn("\n", card)
        self.assertNotIn("\\n", card)

    def test_scan_report_has_readable_sections_and_price_buckets(self):
        result = {
            "market": {
                "regime": "bullish", "nifty_change_1d": -0.5, "nifty_change_5d": 2.3,
                "global_risk": "risk_on", "global_positive_count": 5, "global_count": 6,
                "benchmarks": {"SENSEX": {"daily_pct": -0.3, "weekly_pct": 2, "monthly_pct": 4}},
            },
            "data_date": "2026-11-13", "success_count": 240, "selected_count": 250,
            "nse_selected": 200, "bse_selected": 50, "candidate_count": 8,
            "news_count": 50, "news_sources_working": 11, "news_sources_total": 18,
            "global_news": [], "official_news": [],
            "low": pd.DataFrame([{
                "symbol": "LOW", "company": "Low Co", "exchange": "NSE", "score": 80, "price": 100,
                "change_1d_pct": -0.5, "ret5_pct": 1, "ret20_pct": 2, "entry_low": 98,
                "entry_high": 102, "stop_loss": 95, "target1": 110, "target2": 115,
                "risk": "Controlled", "rsi": 60, "rvol": 2, "setup_status": "Watchlist candidate",
            }]),
            "high": pd.DataFrame(columns=["symbol"]),
        }
        messages = format_scan_messages(result)
        self.assertEqual(len(messages), 5)
        self.assertIn("SCAN SUMMARY", messages[0])
        self.assertIn("GLOBAL EQUITY MARKETS", messages[1])
        self.assertIn("RELEVANT NEWS", messages[2])
        self.assertIn("PRICE ≤ ₹1,000", messages[3])
        self.assertIn("PRICE > ₹1,000", messages[4])
        joined = "\n".join(messages)
        self.assertNotIn("\\n", joined)
        self.assertTrue(all(len(message) <= 4096 for message in messages))
        self.assertIn("LOW", messages[3])


if __name__ == "__main__":
    unittest.main()
