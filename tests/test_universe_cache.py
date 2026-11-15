import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from radar.universe import load_cached_nse_universe, load_cached_bse_universe


class UniverseCacheValidationTests(unittest.TestCase):
    def test_nse_cache_rejects_wrong_exchange_and_malformed_yahoo_ticker(self):
        rows = pd.DataFrame([
            {"symbol": "RELIANCE", "company": "Reliance Industries", "exchange": "NSE",
             "sector": "Unknown", "isin": "INE002A01018", "yahoo_symbol": "RELIANCE.NS"},
            {"symbol": "ABC", "company": "Bad Symbol", "exchange": "NSE",
             "sector": "Unknown", "isin": "INE000A01000", "yahoo_symbol": "https://evil.example/ABC.NS"},
            {"symbol": "500325", "company": "Wrong exchange", "exchange": "BSE",
             "sector": "Unknown", "isin": "INE002A01018", "yahoo_symbol": "500325.BO"},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nse.csv"
            rows.to_csv(path, index=False)
            with patch("radar.universe.NSE_CACHE", path):
                result = load_cached_nse_universe()
        self.assertEqual(result["symbol"].tolist(), ["RELIANCE"])

    def test_bse_cache_requires_numeric_code_and_exact_bo_ticker(self):
        rows = pd.DataFrame([
            {"symbol": "500325", "company": "Reliance Industries", "exchange": "BSE",
             "sector": "Unknown", "isin": "INE002A01018", "yahoo_symbol": "500325.BO"},
            {"symbol": "ABC", "company": "Bad BSE symbol", "exchange": "BSE",
             "sector": "Unknown", "isin": "INE000A01000", "yahoo_symbol": "ABC.BO"},
            {"symbol": "500326", "company": "Mismatched ticker", "exchange": "BSE",
             "sector": "Unknown", "isin": "INE000B01000", "yahoo_symbol": "500325.BO"},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bse.csv"
            rows.to_csv(path, index=False)
            with patch("radar.universe.BSE_CACHE", path):
                result = load_cached_bse_universe()
        self.assertEqual(result["symbol"].tolist(), ["500325"])


if __name__ == "__main__":
    unittest.main()
