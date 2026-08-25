# -*- coding: utf-8 -*-
"""
server.py — 數據獵手看板伺服器（純標準庫，無相依）

開 http://127.0.0.1:8899 看深色 HUD 看板。
看板每 30 秒抓 state.json；state.json 由 scan.py / loop.py 在背景更新。

用法：
  python server.py            # 開在 8899
  python server.py 9000       # 自訂埠
  python server.py --scan     # 開站前先即時掃一輪(產出 state.json)
"""
from __future__ import annotations

import json
import os
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from storage import runtime_path

HERE = Path(__file__).resolve().parent
_INDICES_CACHE: dict = {}          # /api/indices 60 秒 module 快取
_WATCHLIST_CACHE: dict = {}        # 自選股完整資料 20 秒快取
_RUNTIME_FILES = {
    "/state.json": runtime_path("state.json"),
    "/history.json": runtime_path("history.json"),
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(HERE), **k)

    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 16384)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        try:
            obj = json.loads(self.rfile.read(length).decode("utf-8"))
            return obj if isinstance(obj, dict) else {}
        except (ValueError, UnicodeError):
            return {}

    def _watchlist_payload(self, details: bool, live: bool) -> dict:
        import watchlist
        data = watchlist.load_data()
        items, groups = data["items"], data["groups"]
        if not details or not items:
            return {"ok": True, "groups": groups, "items": items, "count": len(items)}

        key = (tuple((x["code"], x.get("group_id")) for x in items), bool(live))
        hit = _WATCHLIST_CACHE.get("value")
        if hit and hit[0] == key and time.monotonic() - hit[1] < 20:
            return hit[2]

        import query
        import risk as risk_mod
        try:
            import realtime_quote
        except Exception:
            realtime_quote = None

        def load_one(item: dict) -> dict:
            code = item["code"]
            try:
                row = query.analyze_stock(code, live=False)
            except Exception as e:
                row = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            if not isinstance(row, dict):
                row = {"ok": False, "error": "無法取得分析資料"}
            row.setdefault("code", code)
            row.setdefault("name", item.get("name") or code)
            row["added_at"] = item.get("added_at")
            row["group_id"] = item.get("group_id") or watchlist.DEFAULT_GROUP_ID
            quote = realtime_quote.fetch_quote(code) if (live and realtime_quote) else None
            if quote:
                row.update({
                    "ok": True,
                    "name": quote.get("name") or row.get("name"),
                    "price": quote.get("price"),
                    "chg": quote.get("chg_pct"),
                    "open": quote.get("open"),
                    "high": quote.get("high"),
                    "low": quote.get("low"),
                    "prev_close": quote.get("prev_close"),
                    "volume": quote.get("volume"),
                    "quote_time": quote.get("time"),
                    "traded": quote.get("traded"),
                    "bid": quote.get("bid"),
                    "ask": quote.get("ask"),
                })
            row.update(risk_mod.quote_metrics(row))
            row["watch_risk"] = risk_mod.assess(row)
            return row

        rows: list[dict | None] = [None] * len(items)
        with ThreadPoolExecutor(max_workers=min(6, len(items))) as pool:
            jobs = {pool.submit(load_one, item): i for i, item in enumerate(items)}
            for job in as_completed(jobs):
                i = jobs[job]
                try:
                    rows[i] = job.result()
                except Exception as e:
                    item = items[i]
                    rows[i] = {"ok": False, "code": item["code"], "name": item.get("name"),
                               "error": f"{type(e).__name__}: {e}"}
        payload = {"ok": True, "groups": groups, "items": rows, "count": len(rows),
                   "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        _WATCHLIST_CACHE["value"] = (key, time.monotonic(), payload)
        return payload

    def _handle_api(self, path: str, qs: dict) -> bool:
        """動態 API：/api/stock、/api/search、/api/analyst。命中回 True(已回應)，否則 False(交還靜態服務)。
        query/analyst 在 handler 內 import(而非模組頂層)，讓查價/分析失敗絕不拖垮靜態看板服務。"""
        if path not in ("/api/stock", "/api/search", "/api/analyst", "/api/news",
                        "/api/quote", "/api/indices", "/api/zones", "/api/watchlist"):
            return False
        if path == "/api/watchlist":
            details = (qs.get("details") or [""])[0].lower() in ("1", "true", "yes")
            live = (qs.get("live") or [""])[0].lower() in ("1", "true", "yes")
            try:
                self._send_json(self._watchlist_payload(details, live))
            except Exception as e:
                self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
            return True
        try:
            import query
        except Exception as e:                       # query 相依缺失 → 只影響 API，不影響看板
            self._send_json({"ok": False, "error": f"query 模組載入失敗：{e}"}, status=500)
            return True

        def _first(key: str) -> str:
            v = qs.get(key)
            return (v[0] if v else "").strip()

        try:
            if path == "/api/search":
                # 前端契約：直接回 JSON 陣列 [{code,name,industry}]；空 q 或出錯回 []（前端好迭代）
                q = _first("q")
                self._send_json(query.search_stocks(q) if q else [])
                return True

            if path == "/api/zones":
                # 交易專區(當沖/短線/長線)：讀盤後/背景產生的快取 zones.json
                try:
                    import zones
                    z = zones.load_zones()
                except Exception:
                    z = None
                self._send_json({"ok": bool(z), **(z or {})})
                return True

            if path == "/api/indices":
                # 大盤主要指數群 + 國際指數；60 秒 module 快取(避免每次輪詢重抓 yfinance)
                import time as _t
                global _INDICES_CACHE
                hit = _INDICES_CACHE.get("v")
                if hit and (_t.monotonic() - hit[0]) < 60:
                    self._send_json(hit[1]); return True
                from concurrent.futures import ThreadPoolExecutor
                twse = intl = []
                try:
                    import realtime_quote as _rq
                    with ThreadPoolExecutor(max_workers=2) as ex:
                        ft = ex.submit(_rq.fetch_indices)
                        fi = ex.submit(_rq.fetch_international)
                        try: twse = ft.result(timeout=8.0) or []
                        except Exception: twse = []
                        try: intl = fi.result(timeout=10.0) or []
                        except Exception: intl = []
                except Exception:
                    pass
                payload = {"ok": True, "twse": twse, "intl": intl}
                _INDICES_CACHE["v"] = (_t.monotonic(), payload)
                self._send_json(payload); return True

            if path == "/api/quote":
                # 即時五檔/報價(證交所 MIS，免費約20秒延遲)：?code= 或 ?q=
                from concurrent.futures import ThreadPoolExecutor
                raw = _first("code") or _first("q")
                code = query._resolve_code(raw) or raw
                q = None; intraday = None
                try:
                    import realtime_quote
                    with ThreadPoolExecutor(max_workers=2) as ex:
                        fq = ex.submit(realtime_quote.fetch_quote, code)
                        fi = ex.submit(realtime_quote.fetch_intraday, code)
                        try:
                            q = fq.result(timeout=8.0)
                        except Exception:
                            q = None
                        try:
                            intraday = fi.result(timeout=8.0)   # 分時走勢(慢一點沒關係)
                        except Exception:
                            intraday = None
                except Exception:
                    q = None
                self._send_json({"ok": bool(q), "quote": q, "intraday": intraday})
                return True

            if path == "/api/news":
                # 個股新聞(Google News RSS)：?code=&name=；有界抓取、短快取，抓不到回空陣列
                from concurrent.futures import ThreadPoolExecutor
                raw = _first("code") or _first("q")
                name = _first("name")
                code = query._resolve_code(raw) or raw
                if not name:
                    try:
                        name = query._meta(code)[0]
                    except Exception:
                        name = ""
                try:
                    import news
                    with ThreadPoolExecutor(max_workers=1) as ex:
                        items = ex.submit(news.load_news, name, code, False, 8).result(timeout=8.0)
                except Exception:
                    items = []
                self._send_json({"ok": True, "items": items or []})
                return True

            if path == "/api/analyst":
                # 金融分析團隊四維度：支援 ?code= 或 ?q=(名稱)。名稱先用 query._resolve_code 轉代號，
                # 再交 analyst.analyze_one(內含四維分析+綜合操作策略)。有界執行(~12s)避免慢網卡死。
                from concurrent.futures import ThreadPoolExecutor
                raw = _first("code") or _first("q")
                if not raw:
                    self._send_json({"ok": False, "error": "缺少 code 或 q"}, status=400)
                    return True
                code = query._resolve_code(raw) or raw
                import analyst
                with ThreadPoolExecutor(max_workers=1) as ex:
                    res = ex.submit(analyst.analyze_one, code).result(timeout=12.0)
                if res is None:
                    self._send_json({"ok": False, "error": f"{code} 無法取得資料"}, status=404)
                else:
                    self._send_json({"ok": True, **res}, status=200)
                return True

            # /api/stock：支援 ?code= 或 ?q=(名稱)；live=1 用即時價
            code = _first("code") or _first("q")
            if not code:
                self._send_json({"ok": False, "error": "缺少 code 或 q"}, status=400)
                return True
            live = _first("live") in ("1", "true", "yes")
            res = query.analyze_stock(code, live=live)
            self._send_json(res, status=200 if res.get("ok") else 404)
        except Exception as e:                        # 任意查詢例外都收斂成 JSON，server 不崩
            self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=500)
        return True

    def do_GET(self):
        split = urlsplit(self.path)
        if self._handle_api(split.path, parse_qs(split.query)):
            return
        runtime_file = _RUNTIME_FILES.get(split.path)
        if runtime_file is not None:
            if not runtime_file.exists():
                # HTTP status reason 只能用 Latin-1；中文放 UTF-8 JSON body，否則
                # Python 3.14 會在 state.json 尚未產生時拋 UnicodeEncodeError。
                self._send_json({"ok": False, "error": "尚無資料"}, 404)
                return
            try:
                body = runtime_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                self._send_json({"ok": False, "error": "讀取資料失敗"}, 500)
            return
        if self.path in ("/", "/index.html", ""):
            self.path = "/dashboard.html"
        return super().do_GET()

    def do_POST(self):
        split = urlsplit(self.path)
        if split.path not in ("/api/watchlist", "/api/watchlist/groups"):
            self.send_error(404)
            return
        try:
            import watchlist
            obj = self._read_json()
            if split.path == "/api/watchlist/groups":
                data = watchlist.create_group(str(obj.get("name", "")))
                status = 201
            else:
                group_id = obj.get("group_id") if "group_id" in obj else None
                _, created = watchlist.add(str(obj.get("code", "")), str(obj.get("name", "")),
                                           None if group_id is None else str(group_id))
                data = watchlist.load_data()
                status = 201 if created else 200
            _WATCHLIST_CACHE.clear()
            self._send_json({"ok": True, **data, "count": len(data["items"])}, status)
        except ValueError as e:
            self._send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def do_PATCH(self):
        split = urlsplit(self.path)
        if split.path not in ("/api/watchlist", "/api/watchlist/groups"):
            self.send_error(404)
            return
        try:
            import watchlist
            qs = parse_qs(split.query)
            obj = self._read_json()
            if split.path == "/api/watchlist/groups":
                group_id = (qs.get("id") or [""])[0]
                data = watchlist.rename_group(group_id, str(obj.get("name", "")))
            else:
                code = (qs.get("code") or [""])[0]
                data = watchlist.move(code, str(obj.get("group_id", "")))
            _WATCHLIST_CACHE.clear()
            self._send_json({"ok": True, **data, "count": len(data["items"])})
        except ValueError as e:
            self._send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def do_DELETE(self):
        split = urlsplit(self.path)
        if split.path not in ("/api/watchlist", "/api/watchlist/groups"):
            self.send_error(404)
            return
        try:
            import watchlist
            qs = parse_qs(split.query)
            if split.path == "/api/watchlist/groups":
                data = watchlist.delete_group((qs.get("id") or [""])[0])
                removed = True
            else:
                _, removed = watchlist.remove((qs.get("code") or [""])[0])
                data = watchlist.load_data()
            _WATCHLIST_CACHE.clear()
            self._send_json({"ok": True, "removed": removed, **data,
                             "count": len(data["items"])})
        except ValueError as e:
            self._send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def end_headers(self):
        # state.json 不要被快取
        if self.path.startswith("/state.json"):
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # 安靜


def main():
    port = int(os.environ.get("RADAR_PORT", "8899"))
    host = os.environ.get("RADAR_HOST", "127.0.0.1")
    do_scan = False
    for a in sys.argv[1:]:
        if a == "--scan":
            do_scan = True
        elif a.isdigit():
            port = int(a)

    if do_scan:
        try:
            import scan
            print("[server] 開站前先掃一輪…")
            scan.run_once(push=False)
        except Exception as e:
            print(f"[server] 預掃失敗（仍照常開站）：{e}")

    # 埠占用 → 自動 +1 重試(比照 app.py 捕捉 OSError)，最多試 10 個埠
    httpd = None
    for p in range(port, port + 10):
        try:
            httpd = ThreadingHTTPServer((host, p), Handler)
            port = p
            break
        except OSError:
            print(f"[server] 埠 {p} 已被占用，改試 {p + 1}…")
            continue
    if httpd is None:
        print(f"[server] 連續 10 個埠({port}-{port + 9})皆被占用，放棄。")
        return

    shown_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
    url = f"http://{shown_host}:{port}/"
    print(f"[server] 數據獵手看板 → {url}")
    print("[server] Ctrl+C 結束")
    try:
        if os.environ.get("RADAR_OPEN_BROWSER", "1").lower() not in ("0", "false", "no"):
            webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] 已停止")


if __name__ == "__main__":
    main()
