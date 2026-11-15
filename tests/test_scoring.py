import unittest
import numpy as np
import pandas as pd

from radar.scoring import score_stock, apply_news_overlay


def synthetic_history(stale_days=0, volume=250_000):
    end = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize() - pd.Timedelta(days=stale_days)
    dates = pd.bdate_range(end=end, periods=90)
    close = np.linspace(100.0, 132.0, len(dates)) + np.sin(np.arange(len(dates)) / 3) * 1.5
    frame = pd.DataFrame(index=dates)
    frame["Close"] = close
    frame["Open"] = close * 0.999
    frame["High"] = close * 1.012
    frame["Low"] = close * 0.988
    frame["Volume"] = volume
    return frame


class RecommendationScoringTests(unittest.TestCase):
    def test_score_is_bounded_and_levels_are_ordered(self):
        scored = score_stock({"symbol": "TEST"}, synthetic_history(),
                             {"regime": "bullish", "nifty_ret20_pct": 1.0, "nifty_ret60_pct": 2.0})
        self.assertGreaterEqual(scored["score"], 0)
        self.assertLessEqual(scored["score"], 100)
        self.assertLess(scored["stop_loss"], scored["price"])
        self.assertGreater(scored["target1"], scored["price"])
        self.assertGreater(scored["target2"], scored["target1"])
        self.assertIn("relative_strength_score", scored)

    def test_stale_data_is_rejected(self):
        scored = score_stock({"symbol": "TEST"}, synthetic_history(stale_days=9),
                             {"regime": "mixed"})
        self.assertFalse(scored["eligible"])
        self.assertEqual(scored["setup_status"], "Reject — stale data")

    def test_low_traded_value_is_rejected(self):
        scored = score_stock({"symbol": "TEST"}, synthetic_history(volume=1000),
                             {"regime": "mixed"})
        self.assertFalse(scored["eligible"])
        self.assertEqual(scored["setup_status"], "Reject — low liquidity")

    def test_news_overlay_is_capped(self):
        positive = [{"sentiment": 1.0, "sentiment_confidence": 1.0, "source_weight": 1.0, "age_hours": 0}]
        negative = [{"sentiment": -1.0, "sentiment_confidence": 1.0, "source_weight": 1.0, "age_hours": 0}]
        up, _, up_delta, up_flags = apply_news_overlay(60, positive)
        down, _, down_delta, down_flags = apply_news_overlay(60, negative)
        unchanged, no_news_score, delta, no_flags = apply_news_overlay(60, [])
        self.assertEqual(up_delta, 5.0)
        self.assertEqual(down_delta, -5.0)
        self.assertEqual(up, 65.0)
        self.assertEqual(down, 55.0)
        self.assertEqual(unchanged, 60.0)
        self.assertIsNone(no_news_score)
        self.assertEqual(delta, 0.0)
        self.assertEqual(up_flags, [])
        self.assertEqual(down_flags, [])
        self.assertEqual(no_flags, [])


if __name__ == "__main__":
    unittest.main()
