#!/bin/bash
# macOS 雙擊版：背景刷新／掃描 + 主看板伺服器 + 自動開瀏覽器。
source "$(cd "$(dirname "$0")" && pwd)/scripts/macos-common.sh" || exit 1
radar_requirements || exit 1
radar_run app.py "$@"
