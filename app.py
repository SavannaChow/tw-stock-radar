# -*- coding: utf-8 -*-
"""
app.py — 台股數據獵手「桌面 app」一鍵啟動

雙擊桌面捷徑就會：
  1. 背景迴圈：每天自動刷一次快取(拉到昨日) → 盤中每2分用『證交所即時價』跟市場同步掃描、
     盤後每30分，偵測新訊號推 ntfy
  2. 開看板伺服器(8899) 並自動打開瀏覽器
關掉這個視窗就停止。不需要 Windows 工作排程。
"""
from __future__ import annotations

import os
import json
import subprocess
import sys
import time
import threading
import webbrowser
from datetime import datetime, date
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))   # indicators / notify / tw_stock_data
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from server import Handler               # 重用看板 handler  # noqa: E402
from storage import runtime_path         # noqa: E402

PORT = int(os.environ.get("RADAR_PORT", "8899"))
HOST = os.environ.get("RADAR_HOST", "127.0.0.1")
FRESHEN_TIMEOUT_SECONDS = 20 * 60
FRESHEN_RETRY_SECONDS = 30 * 60
SCAN_TIMEOUT_SECONDS = 15 * 60
SCAN_RETRY_SECONDS = 2 * 60
ZONES_TIMEOUT_SECONDS = 10 * 60
STATUS_FILE = runtime_path("status.json")
REFRESH_REQUEST_FILE = runtime_path("refresh.request.json")


def _market_hours() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 <= hm <= 13 * 60 + 35


def _write_status(**values) -> None:
    """原子寫入背景工作狀態，讓網頁/維運能判斷是否卡住。"""
    values["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = STATUS_FILE.with_suffix(STATUS_FILE.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATUS_FILE)
    except OSError:
        pass


def _stop_process(proc: subprocess.Popen, label: str) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    print(f"[app] {label}逾時，已停止；稍後會重試")


def worker():
    """監督所有耗時工作；任何資料源卡住，都不能把 app 的背景線卡死。"""
    last_fresh: date | None = None
    zones_day: date | None = None
    freshen_proc: subprocess.Popen | None = None
    freshen_started = 0.0
    freshen_retry_at = 0.0
    scan_proc: subprocess.Popen | None = None
    scan_started = 0.0
    scan_started_at: str | None = None
    next_scan_at = 0.0
    scan_reason = ""
    last_scan: dict = {"result": "尚未執行"}
    zones_proc: subprocess.Popen | None = None
    zones_started = 0.0

    def start_freshen() -> subprocess.Popen:
        """快取刷新獨立程序執行；外部資料源卡住不能拖死看板掃描。"""
        print("[app] 每日刷新快取已在背景啟動…")
        return subprocess.Popen(
            [sys.executable, str(HERE / "scan.py"), "--freshen", "--full"],
            cwd=str(HERE),
        )

    def start_scan(reason: str) -> subprocess.Popen:
        """掃描一定在子程序；遠端資料源斷線時可被監督程序殺掉。"""
        print(f"[app] 啟動{reason}全市場掃描…")
        return subprocess.Popen(
            [sys.executable, str(HERE / "scan.py"), "--full", "--realtime",
             "--no-refresh-if-stale"],
            cwd=str(HERE),
        )

    def start_zones() -> subprocess.Popen:
        print("[app] 交易專區在背景產生…")
        return subprocess.Popen([sys.executable, str(HERE / "zones.py"), "--full"], cwd=str(HERE))

    print("[app] 背景工作監督器啟動（全市場掃描均可逾時停止）")
    while True:
        mh = _market_hours()
        try:
            today = date.today()
            if freshen_proc is not None:
                rc = freshen_proc.poll()
                elapsed = time.monotonic() - freshen_started
                if rc is not None:
                    if rc == 0:
                        last_fresh = today
                        print("[app] 每日快取刷新完成")
                    else:
                        freshen_retry_at = time.monotonic() + FRESHEN_RETRY_SECONDS
                        print(f"[app] 快取刷新失敗（exit {rc}）；30 分鐘後重試")
                    freshen_proc = None
                elif elapsed > FRESHEN_TIMEOUT_SECONDS:
                    _stop_process(freshen_proc, "快取刷新")
                    freshen_retry_at = time.monotonic() + FRESHEN_RETRY_SECONDS
                    freshen_proc = None
            if (freshen_proc is None and last_fresh != today
                    and time.monotonic() >= freshen_retry_at):
                cache_count = len(list((HERE / "cache").glob("*.csv")))
                if cache_count < 500:
                    print(f"[app] ⚠ 快取僅 {cache_count} 檔（期望 1900+）")
                    print("[app] ⚠ 請先執行： python prefill_cache.py")
                freshen_proc = start_freshen()
                freshen_started = time.monotonic()

            # 手動請求是排隊訊號；掃描中的請求保留到下一輪，不丟失。
            manual_requested = REFRESH_REQUEST_FILE.exists()
            if scan_proc is not None:
                rc = scan_proc.poll()
                elapsed = time.monotonic() - scan_started
                if rc is not None:
                    scan_proc = None
                    last_scan = {"result": "完成" if rc == 0 else "失敗", "exit_code": rc,
                                 "reason": scan_reason,
                                 "finished_at": datetime.now().isoformat(timespec="seconds")}
                    if rc == 0:
                        print("[app] 全市場掃描完成")
                        next_scan_at = time.monotonic() + (2 * 60 if _market_hours() else 30 * 60)
                        if zones_day != today and zones_proc is None:
                            zones_proc = start_zones()
                            zones_started = time.monotonic()
                    else:
                        next_scan_at = time.monotonic() + SCAN_RETRY_SECONDS
                        print(f"[app] 全市場掃描失敗（exit {rc}）；2 分鐘後重試")
                elif elapsed > SCAN_TIMEOUT_SECONDS:
                    _stop_process(scan_proc, "全市場掃描")
                    scan_proc = None
                    last_scan = {"result": "逾時停止", "reason": scan_reason,
                                 "finished_at": datetime.now().isoformat(timespec="seconds")}
                    next_scan_at = time.monotonic() + SCAN_RETRY_SECONDS

            if zones_proc is not None:
                rc = zones_proc.poll()
                elapsed = time.monotonic() - zones_started
                if rc is not None:
                    zones_proc = None
                    if rc == 0:
                        zones_day = today
                        print("[app] 交易專區已產生")
                    else:
                        print(f"[app] 交易專區失敗（exit {rc}）；下輪掃描後重試")
                elif elapsed > ZONES_TIMEOUT_SECONDS:
                    _stop_process(zones_proc, "交易專區產生")
                    zones_proc = None

            due = time.monotonic() >= next_scan_at
            if scan_proc is None and (manual_requested or due):
                scan_reason = "手動" if manual_requested else ("盤中" if mh else "例行")
                scan_proc = start_scan(scan_reason)
                scan_started = time.monotonic()
                scan_started_at = datetime.now().isoformat(timespec="seconds")
                if manual_requested:
                    try:
                        REFRESH_REQUEST_FILE.unlink()
                    except FileNotFoundError:
                        pass
            _write_status(
                scan={"running": scan_proc is not None, "reason": scan_reason,
                      "started_at": scan_started_at if scan_proc else None},
                last_scan=last_scan,
                freshen={"running": freshen_proc is not None},
                zones={"running": zones_proc is not None, "completed_for": str(zones_day) if zones_day else None},
                manual_request_queued=REFRESH_REQUEST_FILE.exists(),
            )
        except Exception as e:
            print(f"[app] 本輪錯誤（續跑）：{type(e).__name__}: {e}")
        # 5 秒輪詢一次，讓手動更新不必等到下一個盤中/盤後週期。
        time.sleep(5)


def main():
    threading.Thread(target=worker, daemon=True).start()
    # 埠占用 → 自動 +1 重試(最多 10 個埠)，綁定成功後再開實際埠的瀏覽器
    httpd = None
    port = PORT
    for p in range(PORT, PORT + 10):
        try:
            httpd = ThreadingHTTPServer((HOST, p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print(f"[app] 連續 10 個埠({PORT}-{PORT + 9})皆被占用，無法啟動。")
        input("按 Enter 關閉…")
        return
    shown_host = "127.0.0.1" if HOST in ("", "0.0.0.0", "::") else HOST
    url = f"http://{shown_host}:{port}/"
    print("=" * 46)
    print("  量化阿森 · 台股數據獵手")
    print(f"  看板 → {url}" + (f"（埠 {PORT} 被占用改用 {port}）" if port != PORT else ""))
    print("  關閉此視窗即停止")
    print("=" * 46)
    try:
        if os.environ.get("RADAR_OPEN_BROWSER", "1").lower() not in ("0", "false", "no"):
            webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[app] 已停止")


if __name__ == "__main__":
    main()
