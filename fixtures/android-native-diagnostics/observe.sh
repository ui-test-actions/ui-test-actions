#!/usr/bin/env bash
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
out=$1
serial=emulator-5554
package=com.emeint.android.myservices
device=(adb -s "$serial")
mkdir -p "$out"
component=$("${device[@]}" shell cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.LAUNCHER "$package" | tr -d '\r' | tail -1)
# Establish an unchanged execution baseline before starting any observer.
bash "$here/../android-startup/capture.sh" "$serial" "$package" "$component" "$out/baseline"
"${device[@]}" shell dumpsys dropbox --print data_app_native_crash > "$out/baseline/native-dropbox.txt"
"${device[@]}" shell dumpsys dropbox --print data_app_anr > "$out/baseline/anr-dropbox.txt"
"${device[@]}" shell run-as "$package" id > "$out/run-as.txt" 2>&1 || true
"${device[@]}" root > "$out/adb-root.txt" 2>&1 || true
"${device[@]}" wait-for-device
"${device[@]}" shell 'id; getenforce' > "$out/debug-context.txt"
if ! "${device[@]}" shell id | grep -q 'uid=0'; then
  echo 'Observer blocked: signed release is not debuggable and adbd cannot run as root on this image.' > "$out/debug-blocker.txt"
  exit 0
fi
server="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/18/lib/linux/x86_64/lldb-server"
"${device[@]}" push "$server" /data/local/tmp/native-observer-lldb-server > "$out/server-transfer.txt"
"${device[@]}" shell chmod 755 /data/local/tmp/native-observer-lldb-server
# Record the root-enabled environment separately before debugger attachment.
bash "$here/../android-startup/capture.sh" "$serial" "$package" "$component" "$out/root-context-baseline"
"${device[@]}" shell am force-stop "$package"
"${device[@]}" forward tcp:5039 tcp:5039
"${device[@]}" shell am start -W -n "$component" > "$out/observed-launch.txt" 2>&1 &
launch_pid=$!
target_pid=''
for attempt in $(seq 1 200); do
  target_pid=$("${device[@]}" shell pidof "$package" | tr -d '\r' || true)
  if [[ -n "$target_pid" ]]; then break; fi
  sleep 0.01
done
if [[ -z "$target_pid" ]]; then
  echo 'Target exited before observer could find its PID.' > "$out/debug-blocker.txt"
  wait "$launch_pid" || true
  exit 0
fi
printf '%s\n' "$target_pid" > "$out/observed-pid.txt"
"${device[@]}" shell cat "/proc/$target_pid/maps" > "$out/maps-before-attach.txt" 2>&1 || true
"${device[@]}" shell /data/local/tmp/native-observer-lldb-server gdbserver 127.0.0.1:5039 --attach "$target_pid" > "$out/lldb-server.txt" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for attempt in $(seq 1 100); do
  if grep -q 'Listening' "$out/lldb-server.txt"; then break; fi
  if ! kill -0 "$server_pid" 2>/dev/null; then break; fi
  sleep 0.05
done
export NATIVE_OBSERVATION_FILE="$out/lldb-observations.txt"
timeout 35 lldb -b -o 'gdb-remote 127.0.0.1:5039' \
  -o "script exec(open('$here/lldb-observe.py').read())" \
  -o quit > "$out/lldb-client.txt" 2>&1 || true
wait "$launch_pid" || true
"${device[@]}" shell cat "/proc/$target_pid/maps" > "$out/maps-after-observation.txt" 2>&1 || true
"${device[@]}" logcat -d -b main -b system -b crash -b events -v threadtime > "$out/observed-logcat.txt"
"${device[@]}" shell dumpsys activity exit-info "$package" > "$out/observed-exits.txt"
"${device[@]}" shell am force-stop "$package"
