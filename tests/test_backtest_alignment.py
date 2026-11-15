import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from backtest import run_backtest_for_symbol


class BacktestBenchmarkAlignmentTests(unittest.TestCase):
    def test_nifty_history_is_cut_off_by_stock_date_not_row_number(self):
        stock_dates = pd.bdate_range("2020-01-01", periods=240)
        nifty_dates = pd.bdate_range("2020-06-01", periods=240)
        stock = pd.DataFrame(
            {"Close": np.linspace(100, 140, len(stock_dates))},
            index=stock_dates,
        )
        nifty = pd.DataFrame(
            {"Close": np.linspace(9000, 12000, len(nifty_dates))},
            index=nifty_dates,
        )
        observed_cutoffs = []

        def capture_technical(history, benchmark):
            if benchmark is not None and not benchmark.empty:
                observed_cutoffs.append(benchmark.index.max())
            return {"close": float(history["Close"].iloc[-1])}

        with patch("backtest.ta.analyze", side_effect=capture_technical), \
             patch("backtest.scoring.score_technical", return_value=(10, {})), \
             patch("backtest.scoring.score_momentum", return_value=(10, {})), \
             patch("backtest.scoring.compute_score", return_value={"total_score": 50}):
            rows = run_backtest_for_symbol("TEST", stock, nifty, {})

        self.assertTrue(rows)
        self.assertTrue(observed_cutoffs)
        self.assertTrue(all(date <= stock_dates[-1] for date in observed_cutoffs))
        # The positional slice would have included Nifty dates months after
        # the stock's final observation because the series start on different dates.
        self.assertLess(observed_cutoffs[-1], nifty_dates[200])


if __name__ == "__main__":
    unittest.main()
