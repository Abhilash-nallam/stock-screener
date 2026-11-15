import tempfile
import unittest
from pathlib import Path

import pandas as pd

from radar.ledger import _refresh, read_ledger, save_daily_picks


class ForwardTestLedgerTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.bdate_range("2026-11-16", periods=6)
        self.nse = pd.DataFrame(
            {"Close": [100, 101, 102, 103, 104, 110]},
            index=self.dates,
        )
        self.bse = pd.DataFrame(
            {"Close": [100, 99, 98, 97, 96, 90]},
            index=self.dates,
        )
        self.ledger = pd.DataFrame([
            {"asof_date": str(self.dates[0].date()), "symbol": "ABC",
             "exchange": "NSE", "price": 100, "return_5d_pct": None},
            {"asof_date": str(self.dates[0].date()), "symbol": "ABC",
             "exchange": "BSE", "price": 100, "return_5d_pct": None},
        ])

    def test_same_symbol_on_two_exchanges_uses_separate_history(self):
        refreshed = _refresh(
            self.ledger.copy(),
            {"NSE:ABC": self.nse, "BSE:ABC": self.bse},
        )
        values = dict(zip(refreshed["exchange"], refreshed["return_5d_pct"]))
        self.assertEqual(values["NSE"], 10.0)
        self.assertEqual(values["BSE"], -10.0)

    def test_save_does_not_deduplicate_same_symbol_across_exchanges(self):
        picks = pd.DataFrame([
            {"data_date": str(self.dates[0].date()), "symbol": "ABC", "company": "Alpha",
             "exchange": "NSE", "price": 100, "score": 80, "risk": "Moderate"},
            {"data_date": str(self.dates[0].date()), "symbol": "ABC", "company": "Beta",
             "exchange": "BSE", "price": 200, "score": 81, "risk": "Moderate"},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.csv"
            saved = save_daily_picks(
                picks,
                {"NSE:ABC": self.nse, "BSE:ABC": self.bse},
                "mixed",
                path=path,
            )
            self.assertEqual(len(saved), 2)
            self.assertEqual(set(saved["exchange"]), {"NSE", "BSE"})
            loaded = read_ledger(path)
            self.assertEqual(len(loaded), 2)


if __name__ == "__main__":
    unittest.main()
