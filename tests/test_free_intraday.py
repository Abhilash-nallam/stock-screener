import unittest
from datetime import datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from radar.free_data import fetch_intraday_5m_snapshot, YAHOO_INTRADAY_PROVIDER

IST = ZoneInfo("Asia/Kolkata")


class FreeIntradayTests(unittest.TestCase):
    def _frame(self):
        stamps = pd.date_range(
            "2026-11-16 09:15:00",
            periods=7,
            freq="5min",
            tz=IST,
        )
        return pd.DataFrame(
            {
                "Open": [100, 100.5, 101, 101.2, 101.3, 101.6, 102],
                "High": [100.7, 101, 101.2, 101.5, 101.8, 102, 102.5],
                "Low": [99.9, 100.4, 100.7, 100.95, 101.2, 101.5, 101.9],
                "Close": [100.5, 100.8, 101, 101.3, 101.6, 101.9, 102.3],
                "Volume": [100, 120, 130, 180, 200, 250, 300],
            },
            index=stamps,
        )

    def test_bse_yahoo_symbol_returns_completed_5m_candles(self):
        now = datetime(2026, 11, 16, 9, 47, tzinfo=IST)
        frame = self._frame()
        with patch("radar.free_data.yf.download", return_value=frame) as download:
            result = fetch_intraday_5m_snapshot("500325.BO", now=now)

        self.assertIsNotNone(result)
        download.assert_called_once()
        self.assertEqual(download.call_args.args[0], "500325.BO")
        # 09:45 bar is still forming at 09:47 and must not be used.
        self.assertEqual(len(result["detail"]["candles"]), 6)
        self.assertEqual(result["snapshot"]["price"], 101.9)
        self.assertEqual(result["snapshot"]["price_type"], "last_completed_5m_candle_close")
        self.assertEqual(result["detail"]["provider"], YAHOO_INTRADAY_PROVIDER)
        self.assertLessEqual(result["detail"]["age_seconds"], 180)

    def test_missing_intraday_data_returns_none(self):
        now = datetime(2026, 11, 16, 9, 47, tzinfo=IST)
        with patch("radar.free_data.yf.download", return_value=pd.DataFrame()):
            result = fetch_intraday_5m_snapshot("RELIANCE.NS", now=now)
        self.assertIsNone(result)

    def test_missing_first_session_candle_is_rejected(self):
        now = datetime(2026, 11, 16, 9, 47, tzinfo=IST)
        frame = self._frame().iloc[1:]
        with patch("radar.free_data.yf.download", return_value=frame):
            result = fetch_intraday_5m_snapshot("RELIANCE.NS", now=now)
        self.assertIsNone(result)

    def test_old_completed_candle_is_rejected(self):
        now = datetime(2026, 11, 16, 10, 5, tzinfo=IST)
        frame = self._frame().iloc[:6]
        with patch("radar.free_data.yf.download", return_value=frame):
            result = fetch_intraday_5m_snapshot("RELIANCE.NS", now=now)
        self.assertIsNone(result)

    def test_custom_session_open_supports_special_session(self):
        now = datetime(2026, 11, 8, 14, 55, tzinfo=IST)
        stamps = pd.date_range("2026-11-08 14:20:00", periods=8, freq="5min", tz=IST)
        frame = self._frame()
        frame.index = stamps
        with patch("radar.free_data.yf.download", return_value=frame):
            result = fetch_intraday_5m_snapshot("500325.BO", now=now, session_open="14:20")
        self.assertIsNotNone(result)
        self.assertEqual(result["detail"]["candles"][0]["time"].time(), time(14, 20))

    def test_current_forming_bar_is_excluded(self):
        now = datetime(2026, 11, 16, 9, 46, tzinfo=IST)
        frame = self._frame()
        with patch("radar.free_data.yf.download", return_value=frame):
            result = fetch_intraday_5m_snapshot("RELIANCE.NS", now=now)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["detail"]["candles"]), 6)
        self.assertLess(result["detail"]["candles"][-1]["time"].time(), time(9, 45))


if __name__ == "__main__":
    unittest.main()
