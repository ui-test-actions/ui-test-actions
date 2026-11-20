#!/usr/bin/env bash
set -euo pipefail

target="${1:?choose a target}"
source_dir=verification/real-apps
runner_temp="${RUNNER_TEMP:?RUNNER_TEMP is required}"
if [[ "$target" == windows ]]; then runner_temp=$(cygpath -u "$runner_temp"); fi
app_dir="$runner_temp/ui-real-app"
evidence=real-app-evidence
python "$source_dir/verify.py" prepare "$target" "$app_dir" "$evidence"

case "$target" in
  linux)
    packages=(libegl1 libgl1 libopengl0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-render-util0)
    apt_options=(-o Acquire::Retries=1 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15)
    if ! timeout 90 sudo apt-get "${apt_options[@]}" install -y --no-install-recommends "${packages[@]}"; then
      timeout 90 sudo apt-get "${apt_options[@]}" update
      timeout 90 sudo apt-get "${apt_options[@]}" install -y --no-install-recommends "${packages[@]}"
    fi
    image="$app_dir/NotepadNext-v0.15-x86_64.AppImage"
    chmod +x "$image"
    (cd "$app_dir" && "$image" --appimage-extract >/dev/null)
    ;;
  windows)
    python -m zipfile -e "$app_dir/npp.8.9.9.1.portable.x64.zip" "$app_dir/editor"
    ;;
  macos)
    mount="$app_dir/image"
    mkdir -p "$mount"
    hdiutil attach -readonly -nobrowse -mountpoint "$mount" "$app_dir/CotEditor_7.1.3.dmg"
    trap 'hdiutil detach "$mount" || true' EXIT
    ditto "$mount/CotEditor.app" "$app_dir/CotEditor.app"
    ;;
  android)
    sudo chmod a+rw /dev/kvm
    image='system-images;android-35;google_apis;x86_64'
    tools="$ANDROID_HOME/cmdline-tools/latest/bin"
    "$tools/sdkmanager" emulator "$image" 'platforms;android-35' 'build-tools;35.0.0'
    export PATH="$ANDROID_HOME/platform-tools:$PATH"
    printf '%s\n' "$ANDROID_HOME/platform-tools" >> "$GITHUB_PATH"
    export ANDROID_USER_HOME="$HOME/.android"
    export ANDROID_AVD_HOME="$runner_temp/ui-real-app-avds"
    mkdir -p "$ANDROID_USER_HOME" "$ANDROID_AVD_HOME"
    adb start-server
    echo no | "$tools/avdmanager" create avd --force --name real-app --package "$image" --path "$ANDROID_AVD_HOME/real-app.avd"
    "$ANDROID_HOME/emulator/emulator" -list-avds | grep -Fx real-app
    "$ANDROID_HOME/emulator/emulator" -avd real-app -port 5554 -no-window -no-audio \
      -no-snapshot -no-boot-anim -gpu swiftshader_indirect > "$evidence/emulator.log" 2>&1 &
    emulator_pid=$!
    timeout 360 bash -c 'until [[ "$(adb -s emulator-5554 shell getprop sys.boot_completed 2>/dev/null | tr -d "\r")" == 1 ]]; do kill -0 "$1" || exit 1; sleep 2; done' bash "$emulator_pid"
    adb -s emulator-5554 shell input keyevent KEYCODE_WAKEUP
    adb -s emulator-5554 shell wm dismiss-keyguard
    adb -s emulator-5554 install "$app_dir/net.gsantner.markor-v164-2026.10.0-flavorDefault-release.apk"
    adb -s emulator-5554 shell mkdir -p /sdcard/Documents/ui-test-actions
    adb -s emulator-5554 push "$evidence/document.txt" /sdcard/Documents/ui-test-actions/document.txt
    printf '%s\n' 'REAL_APP_DEVICE=emulator-5554' >> "$GITHUB_ENV"
    ;;
  ios)
    repo=https://github.com/alawyadnan/thought-meadow.git
    ref=e37b169ac000eb895f7d76f61e6bc234a175de25
    git init -q "$app_dir/source"
    git -C "$app_dir/source" fetch --depth 1 "$repo" "$ref"
    git -C "$app_dir/source" checkout --detach FETCH_HEAD
    [[ "$(git -C "$app_dir/source" rev-parse HEAD)" == "$ref" ]]
    xcrun simctl list devices available -j > "$app_dir/devices.json"
    simulator=$(python -c '
import json, sys
runtimes = json.load(open(sys.argv[1], encoding="utf-8"))["devices"]
print(next(
    device["udid"]
    for key in reversed(sorted(runtimes)) if ".iOS-" in key
    for device in runtimes[key]
    if device["name"].startswith("iPhone") and device["isAvailable"]
))
' "$app_dir/devices.json")
    xcrun simctl boot "$simulator"
    xcodebuild -project "$app_dir/source/native/Waraqa.xcodeproj" -scheme Waraqa -configuration Debug \
      -destination "id=$simulator" -derivedDataPath "$app_dir/build" CODE_SIGNING_ALLOWED=NO \
      -quiet build
    xcrun simctl bootstatus "$simulator"
    xcrun simctl install "$simulator" "$app_dir/build/Build/Products/Debug-iphonesimulator/Waraqa.app"
    printf 'REAL_APP_DEVICE=%s\n' "$simulator" >> "$GITHUB_ENV"
    ;;
esac
