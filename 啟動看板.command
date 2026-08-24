#!/bin/bash
# macOS 雙擊版：啟動金融分析團隊看板（預設 http://127.0.0.1:8900）。
source "$(cd "$(dirname "$0")" && pwd)/scripts/macos-common.sh" || exit 1
radar_requirements || exit 1
radar_run team_server.py "$@"
