import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from radar.live_signals import build_live_signal

IST = ZoneInfo("Asia/Kolkata")


def make_candles():
    rows = [
        (100.0, 100.7, 99.9, 100.5, 100),
        (100.5, 101.0, 100.4, 100.8, 120),
        (100.8, 101.2, 100.7, 101.0, 130),
        (101.0, 101.5, 100.95, 101.3, 180),
        (101.3, 101.8, 101.2, 101.6, 200),
        (101.6, 102.0, 101.5, 101.9, 250),
    ]
    return [
        {"open": o, "high": h, "low": l, "close": c, "volume": v}
        for o, h, l, c, v in rows
    ]


class LiveSignalTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 16, 9, 46, tzinfo=IST)
        self.daily = {"price": 100.0, "score": 85.0, "atr_pct": 2.5, "rsi": 60, "ret5_pct": 3, "ret20_pct": 6}
        self.snapshot = {"price": 102.0, "ohlc": {"open": 100.5, "high": 102.0, "low": 100.4, "close": 100.5}}
        self.detail = {
            "quote": {"last_trade_time": int(self.now.timestamp() * 1000)},
            "candles": make_candles(),
        }

    def test_confirmed_bullish_intraday_setup(self):
        result = build_live_signal(
            self.daily, self.snapshot, self.detail, nifty_change_pct=0.3, now=self.now
        )
        self.assertTrue(result["live_eligible"])
        self.assertEqual(result["live_status"], "CONFIRMED WATCHLIST — verify before entry")
        self.assertGreater(result["live_vwap_distance_pct"], 0)
        self.assertGreater(result["live_score"], 68)
        self.assertGreater(result["live_target1"], result["live_price"])

    def test_stale_last_trade_blocks_recommendation(self):
        stale = dict(self.detail)
        stale["quote"] = {"last_trade_time": int((self.now.timestamp() - 600) * 1000)}
        result = build_live_signal(self.daily, self.snapshot, stale, nifty_change_pct=0, now=self.now)
        self.assertFalse(result["live_eligible"])
        self.assertIn("3 minutes", result["live_reason"])

    def test_price_below_vwap_blocks_recommendation(self):
        snapshot = {"price": 100.2, "ohlc": {"open": 100.5, "high": 102, "low": 100.1, "close": 100.5}}
        result = build_live_signal(self.daily, snapshot, self.detail, nifty_change_pct=0, now=self.now)
        self.assertFalse(result["live_eligible"])
        self.assertIn("VWAP", result["live_reason"])

    def test_extreme_opening_gap_blocks_chasing(self):
        snapshot = {"price": 106.0, "ohlc": {"open": 105.0, "high": 106, "low": 104.9, "close": 100.5}}
        result = build_live_signal(self.daily, snapshot, self.detail, nifty_change_pct=0, now=self.now)
        self.assertFalse(result["live_eligible"])
        self.assertIn("gap", result["live_reason"].lower())

    def test_too_few_completed_candles_waits(self):
        detail = {"quote": self.detail["quote"], "candles": make_candles()[:2]}
        result = build_live_signal(self.daily, self.snapshot, detail, nifty_change_pct=0, now=self.now)
        self.assertFalse(result["live_eligible"])
        self.assertIn("need at least 3", result["live_reason"])


if __name__ == "__main__":
    unittest.main()
