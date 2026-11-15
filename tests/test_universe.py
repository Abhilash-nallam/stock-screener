import unittest
import io
import zipfile
import pandas as pd

from radar.universe import combine_universe, select_scan_universe, _parse_bse_scrip_zip


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

    def test_bse_official_scrip_zip_csv_fallback_maps_code_and_isin(self):
        payload = io.BytesIO()
        csv_data = (
            "Scrip Code,Scrip Name,ISIN Code\n"
            "500325,RELIANCE INDUSTRIES LTD,INE002A01018\n"
            "532540,TATA CONSULTANCY SERVICES LTD,INE467B01029\n"
        )
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("BSE_EQ_SCRIP_15112026.csv", csv_data)

        rows = _parse_bse_scrip_zip(payload.getvalue())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["exchange"], "BSE")
        by_code = {row["symbol"]: row for row in rows}
        self.assertEqual(by_code["500325"]["yahoo_symbol"], "500325.BO")
        self.assertEqual(by_code["500325"]["isin"], "INE002A01018")
        self.assertEqual(by_code["532540"]["company"], "TATA CONSULTANCY SERVICES LTD")

    def test_bse_scrip_zip_rejects_unknown_archive_contents(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("other.txt", "not a BSE security master")
        with self.assertRaisesRegex(ValueError, "could not be parsed"):
            _parse_bse_scrip_zip(payload.getvalue())

    def test_only_250_or_500_is_accepted(self):
        with self.assertRaises(ValueError):
            select_scan_universe(pd.DataFrame(), 300)


if __name__ == "__main__":
    unittest.main()
