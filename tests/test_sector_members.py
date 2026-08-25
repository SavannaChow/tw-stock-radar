# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402,F401
import scan  # noqa: E402


class TestSectorMemberRows(unittest.TestCase):
    def test_keeps_all_members_and_sorts_by_score(self):
        members = [
            {"code": "2303", "name": "聯電", "price": 45.2, "chg": -0.5,
             "score": 48.0, "rsi": 44.0, "st": "DOWN", "signal": None},
            {"code": "2330", "name": "台積電", "price": 1100, "chg": 1.2,
             "score": 72.0, "rsi": 61.0, "st": "UP", "signal": "long",
             "consec_buy_days": 3},
            {"code": "2454", "name": "聯發科", "price": 1400, "chg": 0.8,
             "score": 65.0, "rsi": 58.0, "st": "UP", "signal": None},
        ]

        rows = scan._sector_member_rows(members)

        self.assertEqual([x["code"] for x in rows], ["2330", "2454", "2303"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["consec"], 3)
        self.assertEqual(rows[-1]["consec"], 0)
        self.assertEqual(set(rows[0]), {
            "code", "name", "price", "chg", "score", "rsi", "st", "signal", "consec"
        })


if __name__ == "__main__":
    unittest.main()
