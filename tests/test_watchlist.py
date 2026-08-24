# -*- coding: utf-8 -*-
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402,F401
import watchlist  # noqa: E402


class TestWatchlistPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "watchlist.json"
        self.patch = patch.object(watchlist, "WATCHLIST_FILE", self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_add_update_and_remove(self):
        items, created = watchlist.add("2330", "台積電")
        self.assertTrue(created)
        self.assertEqual(items[0]["code"], "2330")
        self.assertTrue(self.path.exists())

        items, created = watchlist.add("2330", "TSMC")
        self.assertFalse(created)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "TSMC")

        items, removed = watchlist.remove("2330")
        self.assertTrue(removed)
        self.assertEqual(items, [])

    def test_duplicate_rows_are_normalized(self):
        self.path.write_text(json.dumps({"items": [
            {"code": "0050", "name": "元大台灣50"},
            {"code": "0050", "name": "duplicate"},
            {"code": " bad code ", "name": "invalid"},
        ]}), encoding="utf-8")
        items = watchlist.load()
        self.assertEqual([(x["code"], x["name"]) for x in items], [("0050", "元大台灣50")])

    def test_invalid_code_rejected_without_writing(self):
        with self.assertRaises(ValueError):
            watchlist.add("../../etc/passwd", "bad")
        self.assertFalse(self.path.exists())

    def test_damaged_file_degrades_to_empty(self):
        self.path.write_text("not-json", encoding="utf-8")
        self.assertEqual(watchlist.load(), [])


if __name__ == "__main__":
    unittest.main()
