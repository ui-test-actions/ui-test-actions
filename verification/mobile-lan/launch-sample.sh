#!/usr/bin/env bash
set -euo pipefail
target="${1:?}"
staging="$RUNNER_TEMP/mobile-lan-sample"
if [[ "$target" == android ]]; then
  adb -s "$LAN_DEVICE" install -r "$staging/sample.apk"
  adb -s "$LAN_DEVICE" shell input keyevent KEYCODE_WAKEUP
  adb -s "$LAN_DEVICE" shell wm dismiss-keyguard
  adb -s "$LAN_DEVICE" shell am start -W -n "$LAN_APP_ID/.MainActivity"
else
  xcrun simctl install "$LAN_DEVICE" "$staging/p2pkit-sample.app"
  xcrun simctl launch "$LAN_DEVICE" "$LAN_APP_ID"
fi
