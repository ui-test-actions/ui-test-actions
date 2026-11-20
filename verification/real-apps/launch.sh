#!/usr/bin/env bash
set -euo pipefail

target="${1:?choose a target}"
runner_temp="${RUNNER_TEMP:?RUNNER_TEMP is required}"
if [[ "$target" == windows ]]; then runner_temp=$(cygpath -u "$runner_temp"); fi
app_dir="$runner_temp/ui-real-app"
evidence="$PWD/real-app-evidence"

case "$target" in
  linux)
    openbox > "$evidence/window-manager.log" 2>&1 &
    "$app_dir/squashfs-root/AppRun" "$evidence/document.txt" > "$evidence/app.log" 2>&1 &
    ;;
  windows)
    "$app_dir/editor/notepad++.exe" -nosession -noPlugin -multiInst "$evidence/document.txt" > "$evidence/app.log" 2>&1 &
    ;;
  macos)
    open -a "$app_dir/CotEditor.app" "$evidence/document.txt"
    ;;
  android)
    adb -s "$REAL_APP_DEVICE" shell am start -W -a android.intent.action.VIEW \
      -n net.gsantner.markor/.activity.DocumentActivity \
      -d file:///sdcard/Documents/ui-test-actions/document.txt -t text/plain
    ;;
  ios)
    xcrun simctl launch "$REAL_APP_DEVICE" com.alawyadnan.waraqa
    ;;
esac
