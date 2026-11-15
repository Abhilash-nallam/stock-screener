import unittest
import pandas as pd

from radar.universe import combine_universe, select_scan_universe


class UniverseSelectionTests(unittest.TestCase):
    def test_combined_universe_prefers_nse_for_matching_isin(self):
        nse = pd.DataFrame([
            {"symbol": "ABC", "company": "ABC Ltd", "exchange": "NSE",
             "sector": "Unknown", "isin": "INE000A01000", "yahoo_symbol": "ABC.NS"}
        ])
        bse = pd.DataFrame([
            {"symbol": "500001", "company": "ABC Ltd", "exchange": "BSE",
             "sector": "Unknown", "isin": "INE000A01000", "yahoo_symbol": "500001.BO"},
            {"symbol": "500002", "company": "XYZ Ltd", "exchange": "BSE",
             "sector": "Unknown", "isin": "INE000B01000", "yahoo_symbol": "500002.BO"},
        ])
        combined = combine_universe(nse, bse)
        self.assertIn("ABC.NS", combined["yahoo_symbol"].tolist())
        self.assertNotIn("500001.BO", combined["yahoo_symbol"].tolist())
        self.assertIn("500002.BO", combined["yahoo_symbol"].tolist())

    def test_250_scan_is_mixed_and_never_exceeds_limit(self):
        nse = pd.DataFrame([
            {"symbol": f"N{i}", "company": f"NSE {i}", "exchange": "NSE",
             "sector": "Unknown", "yahoo_symbol": f"N{i}.NS"}
            for i in range(300)
        ])
        bse = pd.DataFrame([
            {"symbol": str(500000+i), "company": f"BSE {i}", "exchange": "BSE",
             "sector": "Unknown", "yahoo_symbol": f"{500000+i}.BO"}
            for i in range(100)
        ])
        result = select_scan_universe(pd.concat([nse, bse], ignore_index=True), 250)
        self.assertEqual(len(result), 250)
        self.assertEqual((result["exchange"] == "NSE").sum(), 200)
        self.assertEqual((result["exchange"] == "BSE").sum(), 50)

    def test_daily_rotation_changes_the_selected_symbols(self):
        nse = pd.DataFrame([
            {"symbol": f"N{i}", "company": f"NSE {i}", "exchange": "NSE",
             "sector": "Unknown", "yahoo_symbol": f"N{i}.NS"}
            for i in range(500)
        ])
        bse = pd.DataFrame([
            {"symbol": str(500000+i), "company": f"BSE {i}", "exchange": "BSE",
             "sector": "Unknown", "yahoo_symbol": f"{500000+i}.BO"}
            for i in range(100)
        ])
        data = pd.concat([nse, bse], ignore_index=True)
        first = select_scan_universe(data, 250, as_of=pd.Timestamp("2026-11-15").date())
        second = select_scan_universe(data, 250, as_of=pd.Timestamp("2026-11-16").date())
        self.assertNotEqual(first["yahoo_symbol"].tolist(), second["yahoo_symbol"].tolist())
        self.assertEqual((first["exchange"] == "NSE").sum(), 200)
        self.assertEqual((first["exchange"] == "BSE").sum(), 50)

    def test_only_250_or_500_is_accepted(self):
        with self.assertRaises(ValueError):
            select_scan_universe(pd.DataFrame(), 300)


if __name__ == "__main__":
    unittest.main()
