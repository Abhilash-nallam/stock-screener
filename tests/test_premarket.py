import unittest

from radar.premarket import build_opening_assessment


class PreMarketAssessmentTests(unittest.TestCase):
    def test_positive_inputs_produce_bullish_bias(self):
        result = build_opening_assessment({
            "DOW": 0.8, "NASDAQ": 1.1, "SP500": 0.6,
            "ASIA_AVG": 0.5, "GIFT_GAP_PCT": 0.4, "INDIA_VIX": 13.0,
        })
        self.assertEqual(result["direction"], "BULLISH BIAS")
        self.assertEqual(result["confidence"], 82)
        self.assertEqual(result["volatility"], "RELATIVELY LOW")

    def test_negative_inputs_produce_bearish_bias(self):
        result = build_opening_assessment({
            "DOW": -0.8, "NASDAQ": -1.1, "SP500": -0.6,
            "ASIA_AVG": -0.5, "GIFT_GAP_PCT": -0.4, "INDIA_VIX": 19.0,
        })
        self.assertEqual(result["direction"], "BEARISH BIAS")
        self.assertEqual(result["volatility"], "ELEVATED")

    def test_mixed_inputs_are_neutral(self):
        result = build_opening_assessment({
            "DOW": 0.8, "NASDAQ": -0.8, "SP500": 0.1,
            "ASIA_AVG": -0.1, "GIFT_GAP_PCT": None, "INDIA_VIX": 14.0,
        })
        self.assertEqual(result["direction"], "NEUTRAL / MIXED")

    def test_missing_directional_data_fails_closed(self):
        result = build_opening_assessment({"DOW": None, "NASDAQ": None, "SP500": None})
        self.assertEqual(result["direction"], "INSUFFICIENT DATA")
        self.assertEqual(result["confidence"], 0)

    def test_vix_does_not_create_directional_signal(self):
        result = build_opening_assessment({"INDIA_VIX": 25.0})
        self.assertEqual(result["direction"], "INSUFFICIENT DATA")
        self.assertEqual(result["volatility"], "HIGH")

    def test_breadth_is_not_fabricated_preopen(self):
        result = build_opening_assessment({"DOW": 0.5})
        self.assertIn("Not available", result["breadth_status"])


if __name__ == "__main__":
    unittest.main()
