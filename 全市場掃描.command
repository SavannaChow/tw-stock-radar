#!/bin/bash
# macOS 雙擊版：掃描約 1,900 檔上市櫃股票並更新 state.json。
source "$(cd "$(dirname "$0")" && pwd)/scripts/macos-common.sh" || exit 1
radar_requirements || exit 1

"$RADAR_PYTHON" scan.py --full "$@"
status=$?
echo
if [[ $status -eq 0 ]]; then
  echo "全市場掃描完成。"
else
  echo "全市場掃描失敗（狀態碼 $status）。上方訊息是錯誤原因。"
fi
radar_pause
exit "$status"
