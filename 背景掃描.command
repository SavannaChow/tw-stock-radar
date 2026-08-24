#!/bin/bash
# macOS 雙擊版：盤中 5 分／盤後 30 分持續掃描，畫面與 loop.log 同步記錄。
source "$(cd "$(dirname "$0")" && pwd)/scripts/macos-common.sh" || exit 1
radar_requirements || exit 1
radar_run_logged "$RADAR_ROOT/loop.log" loop.py "$@"
