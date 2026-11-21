#!/usr/bin/env bash
set -euo pipefail
if (( $# < 4 )); then
    echo "Usage: capture.sh SERIAL PACKAGE COMPONENT OUTPUT_DIRECTORY [am start arguments]" >&2
    exit 2
fi
serial=$1
package=$2
component=$3
out=$4
shift 4
mkdir -p "$out"
device=(adb -s "$serial")
"${device[@]}" shell am force-stop "$package"
"${device[@]}" shell dumpsys activity exit-info "$package" > "$out/exit-before.txt"
since=$("${device[@]}" shell "date '+%m-%d %H:%M:%S.000'" | tr -d '\r')
date -u +%FT%TZ > "$out/start-utc.txt"
"${device[@]}" shell am start -W -n "$component" "$@" > "$out/launch.txt" 2>&1 || true
for second in 0 2 5 10; do
    case "$second" in
        2|5|10) sleep "$((second - previous))" ;;
    esac
    "${device[@]}" shell pidof "$package" > "$out/pid-$second.txt" || true
    previous=$second
done
"${device[@]}" shell dumpsys activity exit-info "$package" > "$out/exit-after.txt"
"${device[@]}" shell dumpsys activity activities > "$out/activities.txt"
"${device[@]}" logcat -d -b main -b system -b crash -b events -v threadtime -T "$since" > "$out/logcat.txt"
"${device[@]}" exec-out screencap -p > "$out/screen.png"
date -u +%FT%TZ > "$out/end-utc.txt"
