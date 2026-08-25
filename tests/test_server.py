# -*- coding: utf-8 -*-
"""看板伺服器的錯誤回應測試；不開網路、不啟動真正伺服器。"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402,F401
import server  # noqa: E402


class _FakeHandler:
    """只提供 Handler.do_GET 在 runtime file 分支需要的介面。"""

    _send_json = server.Handler._send_json

    def __init__(self, path: str):
        self.path = path
        self.wfile = io.BytesIO()
        self.status = None
        self.headers = {}

    def _handle_api(self, path, qs):
        return False

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


if __name__ == "__main__":
    unittest.main()
