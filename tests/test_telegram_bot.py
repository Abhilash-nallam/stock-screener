import unittest
from unittest.mock import patch, Mock

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

    def test_stock_card_has_entry_stop_and_targets(self):
        row = {
            "symbol": "TEST", "company": "Test Limited", "exchange": "NSE", "score": 82.5,
            "price": 123.45, "ret5_pct": 2.2, "ret20_pct": -1.1,
            "entry_low": 121, "entry_high": 124, "stop_loss": 115,
            "target1": 140, "target2": 150, "risk": "Moderate",
            "rsi": 61, "rvol": 1.8, "setup_status": "Watchlist candidate",
        }
        card = _stock_card(row, 1)
        for text in ("TEST", "Test Limited", "NSE", "₹123.45", "Entry reference", "Stop reference",
                     "T1", "T2", "🔴", "🟢", "🟡"):
            self.assertIn(text, card)

    def test_scan_report_has_two_price_buckets(self):
        import pandas as pd
        result = {
            "market": {"regime": "bullish", "nifty_change_1d": -0.5, "nifty_change_5d": 2.3},
            "data_date": "2026-11-13", "success_count": 240, "selected_count": 250,
            "candidate_count": 8,
            "low": pd.DataFrame([{"symbol":"LOW","company":"Low Co","score":80,"price":100,
                "ret5_pct":1,"ret20_pct":2,"entry_low":98,"entry_high":102,"stop_loss":95,
                "target1":110,"target2":115,"risk":"Controlled","rsi":60,"rvol":2,
                "setup_status":"Watchlist candidate"}]),
            "high": pd.DataFrame(columns=["symbol"]),
        }
        messages = format_scan_messages(result)
        self.assertEqual(len(messages), 4)
        self.assertIn("PRICE ≤ ₹1,000", messages[1])
        self.assertIn("PRICE > ₹1,000", messages[2])
        self.assertIn("LOW", messages[1])


if __name__ == "__main__":
    unittest.main()
