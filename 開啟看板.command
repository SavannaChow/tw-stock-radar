#!/bin/bash
# macOS 雙擊版：先掃描一輪，再啟動 http://127.0.0.1:8899 看板並開啟瀏覽器。
source "$(cd "$(dirname "$0")" && pwd)/scripts/macos-common.sh" || exit 1
radar_requirements || exit 1
radar_run server.py --scan "$@"
