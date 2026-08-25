# -*- coding: utf-8 -*-
"""看板伺服器的錯誤回應測試；不開網路、不啟動真正伺服器。"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402,F401
import server  # noqa: E402
import watchlist  # noqa: E402


class _FakeHandler:
    """只提供 Handler.do_GET 在 runtime file 分支需要的介面。"""

    _send_json = server.Handler._send_json

    def __init__(self, path: str, body: dict | None = None):
        self.path = path
        self.wfile = io.BytesIO()
        self.status = None
        self.headers = {}
        self.body = body or {}

    def _handle_api(self, path, qs):
        return False

    def _read_json(self):
        return self.body

    def send_response(self, status):
        # 關鍵契約：只傳數字狀態碼，不把中文塞入 HTTP reason phrase。
        self.status = status

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass


class TestRuntimeFileErrors(unittest.TestCase):
    def test_missing_state_returns_utf8_json_without_non_ascii_reason(self):
        original = server._RUNTIME_FILES
        try:
            with tempfile.TemporaryDirectory() as tmp:
                server._RUNTIME_FILES = {"/state.json": Path(tmp) / "missing.json"}
                handler = _FakeHandler("/state.json")
                server.Handler.do_GET(handler)
        finally:
            server._RUNTIME_FILES = original

        self.assertEqual(handler.status, 404)
        self.assertEqual(handler.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertIn("尚無資料", handler.wfile.getvalue().decode("utf-8"))


class TestWatchlistGroupAPI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "watchlist.json"
        self.patch = patch.object(watchlist, "WATCHLIST_FILE", self.path)
        self.patch.start()
        server._WATCHLIST_CACHE.clear()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()
        server._WATCHLIST_CACHE.clear()

    @staticmethod
    def payload(handler):
        return json.loads(handler.wfile.getvalue().decode("utf-8"))

    def test_create_move_and_delete_group(self):
        watchlist.add("2634", "漢翔")

        create = _FakeHandler("/api/watchlist/groups", {"name": "航太股"})
        server.Handler.do_POST(create)
        created = self.payload(create)
        self.assertEqual(create.status, 201)
        group = next(g for g in created["groups"] if g["name"] == "航太股")

        move = _FakeHandler(f"/api/watchlist?code=2634", {"group_id": group["id"]})
        server.Handler.do_PATCH(move)
        moved = self.payload(move)
        self.assertEqual(move.status, 200)
        self.assertEqual(moved["items"][0]["group_id"], group["id"])

        delete = _FakeHandler(f"/api/watchlist/groups?id={group['id']}")
        server.Handler.do_DELETE(delete)
        deleted = self.payload(delete)
        self.assertEqual(delete.status, 200)
        self.assertEqual(deleted["items"][0]["group_id"], watchlist.DEFAULT_GROUP_ID)

    def test_get_watchlist_returns_groups(self):
        watchlist.create_group("記憶體股")
        handler = _FakeHandler("/api/watchlist")
        payload = server.Handler._watchlist_payload(handler, details=False, live=False)
        self.assertEqual(payload["groups"][0]["name"], "記憶體股")
        self.assertEqual(payload["groups"][-1]["id"], watchlist.DEFAULT_GROUP_ID)

    def test_live_watchlist_uses_delayed_ohlcv_when_mis_fails(self):
        watchlist.add("0050", "元大台灣50")
        fallback = {
            "price": 103.75, "chg_pct": None,
            "open": 104.0, "high": 104.2, "low": 103.5, "volume": 12345,
            "prev_close": None, "time": "13:14:00", "traded": True,
            "bid": [], "ask": [], "source": "yfinance_1m", "delayed": True,
        }
        base = {"ok": True, "code": "0050", "name": "元大台灣50",
                "price": 103.8, "chg": -0.81}
        with patch("query.analyze_stock", return_value=base), \
             patch("realtime_quote.fetch_quote", return_value=None), \
             patch("realtime_quote.fetch_intraday_quote", return_value=fallback), \
             patch("risk.quote_metrics", return_value={}), \
             patch("risk.assess", return_value={}):
            payload = server.Handler._watchlist_payload(_FakeHandler("/api/watchlist"),
                                                        details=True, live=True)
        row = payload["items"][0]
        self.assertEqual(row["open"], 104.0)
        self.assertEqual(row["volume"], 12345)
        self.assertEqual(row["chg"], -0.81)  # 備援沒有昨收時保留既有漲跌幅
        self.assertEqual(row["quote_source"], "yfinance_1m")
        self.assertTrue(row["quote_delayed"])


if __name__ == "__main__":
    unittest.main()
