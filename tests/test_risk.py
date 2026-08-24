# -*- coding: utf-8 -*-
"""自選股風險快篩純函式測試；不連網。"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402,F401
import risk  # noqa: E402


def _history(closes, volume=1_000_000):
    close = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "open": close * 0.998,
        "high": close * 1.012,
        "low": close * 0.988,
        "close": close,
        "volume": np.full(len(close), volume, dtype=float),
    }, index=pd.date_range("2026-01-01", periods=len(close), freq="B"))


class TestHistoryMetrics(unittest.TestCase):
    def test_calculates_comparable_risk_metrics(self):
        result = risk.history_metrics(_history(np.linspace(80, 120, 140)))
        self.assertGreater(result["avg_turnover_20"], 100_000_000)
        self.assertEqual(result["avg_volume_20_lots"], 1000)
        self.assertGreater(result["atr_pct"], 0)
        self.assertEqual(result["max_drawdown_60"], 0.0)
        self.assertGreater(result["ma60_gap_pct"], 0)
        self.assertGreater(result["ma60_slope_10d_pct"], 0)
        self.assertEqual(result["from_52w_high_pct"], 0.0)

    def test_short_history_degrades_to_none(self):
        result = risk.history_metrics(_history([100] * 10))
        self.assertTrue(all(value is None for value in result.values()))


class TestQuoteMetrics(unittest.TestCase):
    def test_best_bid_ask_spread(self):
        result = risk.quote_metrics({
            "bid": [{"price": 99.5, "vol": 10}],
            "ask": [{"price": 100.0, "vol": 8}],
        })
        self.assertEqual(result["best_bid"], 99.5)
        self.assertEqual(result["best_ask"], 100.0)
        self.assertEqual(result["bid_ask_spread_pct"], 0.5)

    def test_missing_book_is_unknown(self):
        self.assertIsNone(risk.quote_metrics({})["bid_ask_spread_pct"])


class TestAssessment(unittest.TestCase):
    def _base(self):
        return {
            "code": "2330",
            "avg_turnover_20": 500_000_000,
            "avg_volume_20_lots": 10_000,
            "bid_ask_spread_pct": 0.1,
            "atr_pct": 1.8,
            "max_drawdown_60": -8,
            "ma60_gap_pct": 3,
            "ma60_slope_10d_pct": 1,
            "ma20_distance_atr": 0.8,
            "chip_net_n": 1000,
            "margin_chg": -50,
            "eps_ttm": 35,
            "rev_yoy": 12,
            "op_margin": 40,
        }

    def test_no_obvious_warning(self):
        result = risk.assess(self._base())
        self.assertEqual(result["level"], "ok")
        self.assertEqual(result["label"], "暫無明顯警訊")
        self.assertEqual(len(result["categories"]), 5)

    def test_multiple_red_flags_are_explained(self):
        row = self._base()
        row.update({
            "avg_turnover_20": 10_000_000,
            "bid_ask_spread_pct": 0.8,
            "atr_pct": 6.2,
            "max_drawdown_60": -25,
            "ma60_gap_pct": -12,
            "ma60_slope_10d_pct": -3,
            "ma20_distance_atr": 3.5,
            "chip_net_n": -30_000,
            "margin_chg": 500,
            "eps_ttm": -2,
            "rev_yoy": -25,
        })
        result = risk.assess(row)
        self.assertEqual(result["level"], "high")
        self.assertGreaterEqual(result["high_count"], 4)
        self.assertLessEqual(len(result["reasons"]), 3)
        self.assertIn("20日平均成交金額偏低", result["reasons"])

    def test_missing_data_never_becomes_safe(self):
        result = risk.assess({"code": "2330"})
        self.assertEqual(result["level"], "unknown")
        self.assertEqual(result["unknown_count"], 5)
        self.assertIn("不能視為低風險", result["reasons"][0])

    def test_etf_fundamentals_are_not_scored_as_missing(self):
        row = self._base()
        row.update({"code": "0050", "eps_ttm": None, "rev_yoy": None, "op_margin": None})
        result = risk.assess(row)
        fund = next(x for x in result["categories"] if x["key"] == "fundamentals")
        self.assertEqual(fund["level"], "na")
        self.assertEqual(result["unknown_count"], 0)


if __name__ == "__main__":
    unittest.main()
