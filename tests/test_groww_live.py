import unittest
from unittest.mock import Mock, patch

from radar.groww_live import create_access_token, parse_ohlc, normalise_5m_candles
from datetime import datetime
from zoneinfo import ZoneInfo


class GrowwLiveAdapterTests(unittest.TestCase):
    def test_create_access_token_reads_documented_payload_token(self):
        response = Mock()
        response.json.return_value = {
            "status": "SUCCESS",
            "payload": {
                "token": "session-token-123",
                "tokenRefId": "ref-123",
                "isActive": True,
            },
        }
        with patch("radar.groww_live.requests.post", return_value=response) as post:
            token = create_access_token("api-key", "api-secret")

        self.assertEqual(token, "session-token-123")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer api-key")
        self.assertEqual(kwargs["headers"]["X-API-VERSION"], "1.0")
        self.assertEqual(kwargs["json"]["key_type"], "approval")
        self.assertEqual(len(kwargs["json"]["checksum"]), 64)

    def test_ohlc_parser_handles_groww_documented_string_format(self):
        result = parse_ohlc("{open: 149.50,high: 150.50,low: 148.50,close: 149.50}")
        self.assertEqual(result, {"open": 149.5, "high": 150.5, "low": 148.5, "close": 149.5})

    def test_five_minute_candles_parse_iso_timestamps_and_exclude_current_bar(self):
        ist = ZoneInfo("Asia/Kolkata")
        now = datetime(2026, 11, 16, 9, 46, tzinfo=ist)
        rows = [
            ["2026-11-16T09:35:00", 100, 101, 99, 100.5, 120],
            ["2026-11-16T09:40:00", 100.5, 101.5, 100, 101.2, 150],
            ["2026-11-16T09:45:00", 101.2, 102, 101, 101.8, 170],
        ]
        candles = normalise_5m_candles(rows, now)
        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[-1]["close"], 101.2)


if __name__ == "__main__":
    unittest.main()
