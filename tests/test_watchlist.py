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

    def test_version_one_migrates_without_losing_items(self):
        self.path.write_text(json.dumps({"version": 1, "items": [
            {"code": "2330", "name": "台積電", "added_at": "2026-01-02T03:04:05"},
        ]}), encoding="utf-8")
        data = watchlist.load_data()
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["items"][0]["code"], "2330")
        self.assertEqual(data["items"][0]["group_id"], watchlist.DEFAULT_GROUP_ID)
        self.assertEqual(data["items"][0]["added_at"], "2026-01-02T03:04:05")
        self.assertEqual(data["groups"][-1]["name"], "未分類")

    def test_group_lifecycle_and_move(self):
        watchlist.add("2634", "漢翔")
        data = watchlist.create_group("航太股")
        group = next(g for g in data["groups"] if g["name"] == "航太股")

        data = watchlist.move("2634", group["id"])
        self.assertEqual(data["items"][0]["group_id"], group["id"])

        data = watchlist.rename_group(group["id"], "航太與軍工")
        self.assertIn("航太與軍工", [g["name"] for g in data["groups"]])

        data = watchlist.delete_group(group["id"])
        self.assertEqual(data["items"][0]["group_id"], watchlist.DEFAULT_GROUP_ID)
        self.assertEqual(data["items"][0]["code"], "2634")

    def test_group_validation(self):
        with self.assertRaisesRegex(ValueError, "不可空白"):
            watchlist.create_group("   ")
        watchlist.create_group("記憶體股")
        with self.assertRaisesRegex(ValueError, "已存在"):
            watchlist.create_group(" 記憶體股 ")
        with self.assertRaisesRegex(ValueError, "不可重新命名"):
            watchlist.rename_group(watchlist.DEFAULT_GROUP_ID, "其他")
        with self.assertRaisesRegex(ValueError, "不可刪除"):
            watchlist.delete_group(watchlist.DEFAULT_GROUP_ID)

    def test_add_to_group_and_unknown_group_rejected(self):
        data = watchlist.create_group("記憶體股")
        group = next(g for g in data["groups"] if g["name"] == "記憶體股")
        items, created = watchlist.add("2344", "華邦電", group["id"])
        self.assertTrue(created)
        self.assertEqual(items[0]["group_id"], group["id"])
        with self.assertRaisesRegex(ValueError, "不存在"):
            watchlist.add("2330", "台積電", "g_000000000000")

    def test_delete_group_persists_fallback(self):
        data = watchlist.create_group("測試分類")
        group = next(g for g in data["groups"] if g["name"] == "測試分類")
        watchlist.add("2330", "台積電", group["id"])
        watchlist.delete_group(group["id"])

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], 2)
        self.assertEqual(raw["items"][0]["group_id"], watchlist.DEFAULT_GROUP_ID)


if __name__ == "__main__":
    unittest.main()
