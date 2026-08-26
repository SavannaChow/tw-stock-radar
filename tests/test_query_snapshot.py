import unittest

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


if __name__ == "__main__":
    unittest.main()
