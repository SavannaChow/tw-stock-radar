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

import scan                              # noqa: E402
from server import Handler               # 重用看板 handler  # noqa: E402

PORT = int(os.environ.get("RADAR_PORT", "8899"))
HOST = os.environ.get("RADAR_HOST", "127.0.0.1")
FRESHEN_TIMEOUT_SECONDS = 20 * 60
FRESHEN_RETRY_SECONDS = 30 * 60


def _market_hours() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 <= hm <= 13 * 60 + 35


def worker():
    """背景掃描迴圈：每天刷快取 + 即時同步掃描 + 推播 + 每日全市場交易專區。"""
    rows = scan.load_full_universe()     # 全市場(~1900 檔上市櫃)
    last_fresh: date | None = None
    zones_day: date | None = None
    freshen_proc: subprocess.Popen | None = None
    freshen_started = 0.0
    freshen_retry_at = 0.0

    def start_freshen() -> subprocess.Popen:
        """快取刷新獨立程序執行；外部資料源卡住不能拖死看板掃描。"""
        print("[app] 每日刷新快取已在背景啟動…")
        return subprocess.Popen(
            [sys.executable, str(HERE / "scan.py"), "--freshen", "--full"],
            cwd=str(HERE),
        )

    print(f"[app] 背景掃描啟動（全市場 {len(rows)} 檔）")
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
                    freshen_proc.terminate()
                    try:
                        freshen_proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        freshen_proc.kill()
                    freshen_retry_at = time.monotonic() + FRESHEN_RETRY_SECONDS
                    freshen_proc = None
                    print("[app] 快取刷新超過 20 分鐘，已停止；30 分鐘後重試")
            if (freshen_proc is None and last_fresh != today
                    and time.monotonic() >= freshen_retry_at):
                cache_count = len(list(scan.CACHE_DIR.glob("*.csv")))
                if cache_count < 500:
                    print(f"[app] ⚠ 快取僅 {cache_count} 檔（期望 1900+）")
                    print("[app] ⚠ 請先執行： python prefill_cache.py")
                freshen_proc = start_freshen()
                freshen_started = time.monotonic()
            # 快取刷新在獨立程序進行，主看板永遠先以既有快取寫出最新 state.json。
            scan.run_once(push=True, realtime=True, refresh_if_stale=False)
            # 交易專區(當沖/短線/長線 全市場選股)：每日建一次(選股非 tick 敏感，~30s 不卡看板)
            if zones_day != today:
                try:
                    import zones
                    z = zones.build_zones(full=True, use_cache_only=True)
                    print(f"[app] 交易專區已產生（全市場 {z['universe_n']} 檔）")
                    zones_day = today
                except Exception as e:
                    print(f"[app] 交易專區產生略過：{type(e).__name__}: {e}")
        except Exception as e:
            print(f"[app] 本輪錯誤（續跑）：{type(e).__name__}: {e}")
        wait = 2 if mh else 30
        print(f"[app] {datetime.now():%H:%M:%S} 本輪結束，{wait} 分後再掃（{'盤中即時' if mh else '盤後'}）")
        time.sleep(wait * 60)


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
