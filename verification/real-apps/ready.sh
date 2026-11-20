#!/usr/bin/env bash
set -euo pipefail

case "${1:?choose a target}" in
  linux)
    xdotool search --onlyvisible --name '^Notepad Next$' >/dev/null
    ;;
  windows)
    tasklist.exe | grep -Fi 'notepad++.exe' >/dev/null
    ;;
  macos)
    pgrep -x CotEditor >/dev/null
    ;;
  android)
    adb -s "$REAL_APP_DEVICE" shell pidof net.gsantner.markor >/dev/null
    ;;
  ios)
    xcrun simctl spawn "$REAL_APP_DEVICE" launchctl list | grep -F 'UIKitApplication:com.alawyadnan.waraqa' >/dev/null
    ;;
esac
