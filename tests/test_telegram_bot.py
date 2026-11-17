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
            "live_price": 125.50, "live_score": 84.0,
            "live_status": "CONFIRMED WATCHLIST — verify before entry",
            "live_quote_time": "09:45:00 IST", "live_quote_age_seconds": 5,
            "live_change_pct": 1.65, "live_gap_pct": 0.5, "live_intraday_pct": 1.1,
            "live_vwap": 124.8, "live_vwap_distance_pct": 0.56,
            "live_5m_momentum_pct": 0.4, "live_relative_strength_pct": 0.7,
            "live_entry_low": 125.2, "live_entry_high": 125.8,
            "live_stop": 121.0, "live_target1": 130.0, "live_target2": 134.0,
            "live_reason": "Price above session VWAP and positive completed 5-minute momentum",
            "atr_pct": 2.2,
        }
        card = _stock_card(row, 1)
        for text in ("TEST", "Test Limited", "Latest 5m close", "Intraday score", "Entry zone",
                     "Stop reference", "Targets", "RSI", "Confirmation", "CONFIRMED WATCHLIST"):
            self.assertIn(text, card)
        self.assertIn("\n", card)
        self.assertNotIn("\\n", card)
        self.assertIn("RSI 61.0", card)
        self.assertIn("ATR 2.20%", card)
        self.assertNotIn("RSI ₹", card)

    def test_scan_report_has_readable_sections_and_price_buckets(self):
        result = {
            "market_session": {"phase": "open", "local_time": "09:46:00"},
            "market": {
                "regime": "bullish", "nifty_change_1d": -0.5, "nifty_change_5d": 2.3,
                "global_risk": "risk_on", "global_positive_count": 5, "global_count": 6,
                "benchmarks": {"SENSEX": {"daily_pct": -0.3, "weekly_pct": 2, "monthly_pct": 4}},
            },
            "data_date": "2026-11-13", "success_count": 240, "selected_count": 250,
            "nse_selected": 200, "bse_selected": 50, "candidate_count": 8,
            "news_count": 50, "news_sources_working": 11, "news_sources_total": 18,
            "global_news": [], "official_news": [],
            "live_ready": True, "live_provider": "Groww Live Data API",
            "live_coverage_pct": 90.0, "live_coverage_count": 180, "live_coverage_total": 200,
            "live_nifty_change_pct": 0.5,
            "live_breadth": {"advances": 120, "declines": 60, "unchanged": 20},
            "live_researched_count": 20, "live_confirmed_count": 5, "live_wait_count": 15,
            "low": pd.DataFrame([{
                "symbol": "LOW", "company": "Low Co", "exchange": "NSE", "score": 80, "price": 100,
                "live_price": 101, "live_score": 82.5, "live_status": "CONFIRMED WATCHLIST — verify before entry",
                "live_quote_time": "09:45:00 IST", "live_quote_age_seconds": 4,
                "live_change_pct": 1.0, "live_gap_pct": 0.3, "live_intraday_pct": 0.7,
                "live_vwap": 100.5, "live_vwap_distance_pct": 0.5, "live_5m_momentum_pct": 0.4,
                "live_relative_strength_pct": 0.6, "live_entry_low": 100.8, "live_entry_high": 101.2,
                "live_stop": 98, "live_target1": 104, "live_target2": 106,
                "live_reason": "Price above VWAP; positive 5-minute momentum",
                "change_1d_pct": -0.5, "ret5_pct": 1, "ret20_pct": 2, "atr_pct": 2.5,
                "risk": "Controlled", "rsi": 60, "rvol": 2, "setup_status": "Watchlist candidate",
            }]),
            "high": pd.DataFrame(columns=["symbol"]),
        }
        messages = format_scan_messages(result)
        self.assertEqual(len(messages), 8)
        self.assertIn("FREE INTRADAY SCAN", messages[0])
        self.assertIn("GLOBAL EQUITY MARKETS", messages[1])
        self.assertIn("RELEVANT NEWS", messages[2])
        self.assertIn("DELIVERY / SWING WATCHLIST", messages[3])
        self.assertIn("DELIVERY / SWING WATCHLIST", messages[4])
        self.assertIn("OPENING GAP CLASSIFICATION", messages[5])
        self.assertIn("OBSERVED GAP-UP", messages[5])
        self.assertIn("OBSERVED GAP-DOWN", messages[5])
        self.assertIn("INTRADAY-CONFIRMED", messages[6])
        self.assertIn("INTRADAY-CONFIRMED", messages[7])
        joined = "\n".join(messages)
        self.assertNotIn("\\n", joined)
        self.assertTrue(all(len(message) <= 4096 for message in messages))
        self.assertIn("LOW", messages[6])


    def test_closed_market_report_shows_daily_delivery_candidates(self):
        result = {
            "market_session": {"phase": "post_market", "local_date": "2026-11-16"},
            "data_date": "2026-11-16", "success_count": 245, "selected_count": 250,
            "candidate_count": 9, "delivery_low": pd.DataFrame([{
                "symbol": "DELIVERY", "company": "Delivery Co", "exchange": "NSE",
                "price": 250.0, "score": 84.0, "change_1d_pct": 1.2,
                "ret5_pct": 3.1, "ret20_pct": 8.4, "ret60_pct": 15.0,
                "rsi": 61, "adx": 28, "distance_55d_high_pct": -1.5,
                "turnover20": 125000000, "rvol": 1.6,
                "entry_low": 245, "entry_high": 252, "stop_loss": 235,
                "target1": 270, "target2": 285, "risk": "Moderate",
                "data_date": "2026-11-16", "news": [], "news_flags": [],
            }]),
            "delivery_high": pd.DataFrame(columns=["symbol"]),
        }
        messages = format_scan_messages(result)
        self.assertIn("DAILY DELIVERY RESEARCH", messages[0])
        self.assertIn("DELIVERY", messages[1])
        self.assertIn("Daily score", messages[1])
        self.assertIn("not an intraday buy signal", messages[1])
        self.assertIn("No candidate passed", messages[2])


    def test_opening_gap_classification_uses_measured_open_gap(self):
        from telegram_bot import _opening_gap_message
        result = {
            "gap_up": pd.DataFrame([{"symbol": "UP", "company": "Up Co", "live_gap_pct": 2.1, "live_price": 102, "score": 82, "live_status": "WAIT"}]),
            "gap_down": pd.DataFrame([{"symbol": "DOWN", "company": "Down Co", "live_gap_pct": -1.4, "live_price": 98, "score": 75, "live_status": "WAIT"}]),
        }
        message = _opening_gap_message(result)
        self.assertIn("measured from the session open", message)
        self.assertIn("UP", message)
        self.assertIn("DOWN", message)
        self.assertIn("2.10%", message)
        self.assertIn("-1.40%", message)

if __name__ == "__main__":
    unittest.main()
