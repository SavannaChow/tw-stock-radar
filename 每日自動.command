#!/bin/bash
# macOS 雙擊版：每個交易日 17:00 自動執行完整盤後流程。
source "$(cd "$(dirname "$0")" && pwd)/scripts/macos-common.sh" || exit 1
radar_requirements || exit 1
radar_run auto_eod.py "$@"
