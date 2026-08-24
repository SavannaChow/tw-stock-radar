#!/bin/bash
# macOS .command launchers shared setup. This file is sourced, not run directly.

RADAR_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RADAR_ROOT" || exit 1

if [[ -x "$RADAR_ROOT/.venv/bin/python" ]]; then
  RADAR_PYTHON="$RADAR_ROOT/.venv/bin/python"
elif [[ -x "$RADAR_ROOT/venv/bin/python" ]]; then
  RADAR_PYTHON="$RADAR_ROOT/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  RADAR_PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  RADAR_PYTHON="$(command -v python)"
else
  echo "找不到 Python。請先安裝 Python 3.9 以上版本。"
  echo "https://www.python.org/downloads/macos/"
  read -r -p "按 Enter 關閉…"
  exit 1
fi

export PYTHONUTF8=1

radar_pause() {
  if [[ -t 0 ]]; then
    read -r -p "按 Enter 關閉視窗…"
  fi
}

radar_requirements() {
  if "$RADAR_PYTHON" -c "import numpy, pandas, requests, twstock, yfinance" >/dev/null 2>&1; then
    return 0
  fi
  echo
  echo "尚未安裝完整 Python 套件。請先在 Terminal 執行："
  printf "  cd %q\n" "$RADAR_ROOT"
  printf "  %q -m pip install -r requirements.txt\n" "$RADAR_PYTHON"
  echo
  radar_pause
  return 1
}

radar_run() {
  "$RADAR_PYTHON" "$@"
  local status=$?
  if [[ $status -ne 0 && $status -ne 130 ]]; then
    echo
    echo "執行失敗（狀態碼 $status）。上方訊息是錯誤原因。"
    radar_pause
  fi
  return "$status"
}

radar_run_logged() {
  local log_file="$1"
  shift
  set -o pipefail
  "$RADAR_PYTHON" "$@" 2>&1 | tee -a "$log_file"
  local status=${PIPESTATUS[0]}
  if [[ $status -ne 0 && $status -ne 130 ]]; then
    echo
    echo "執行失敗（狀態碼 $status）。紀錄已寫入 $log_file。"
    radar_pause
  fi
  return "$status"
}
