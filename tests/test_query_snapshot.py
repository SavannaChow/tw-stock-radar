import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import query


class QuerySnapshotTests(unittest.TestCase):
    @staticmethod
    def _history():
        close = np.arange(1.0, 31.0)
        return pd.DataFrame({
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(30, 2_345_000),
        })

    def test_full_indicators_include_ma10(self):
        result = query._full_indicators(self._history(), live=False)
        self.assertEqual(result["ma10"], 25.5)
        self.assertEqual(result["ma20"], 20.5)
        self.assertIsNone(result["ma60"])

    def test_latest_session_returns_ohlcv_in_lots(self):
        result = query._latest_session(self._history())
        self.assertEqual(result, {
            "open": 29.5,
            "high": 31.0,
            "low": 29.0,
            "volume": 2345,
        })

    def test_stale_cache_is_used_when_refresh_fails(self):
        frame = self._history()
        frame.index = pd.date_range("2026-08-01", periods=len(frame), freq="B")
        query._DF_MEMO.clear()
        with patch("query.scan._read_cache", return_value=frame), \
             patch("query.scan._bulk_yf", return_value={}):
            result = query._load_df("2330", live=False, yf_timeout=0.01)
        self.assertIs(result, frame)


if __name__ == "__main__":
    unittest.main()
