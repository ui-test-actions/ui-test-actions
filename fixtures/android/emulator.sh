#!/usr/bin/env bash
# Source from a workflow step to retain its SDK environment.
boot_fixture_emulator() {
  local name="$1" log="$2"
  local image='system-images;android-35;google_apis;x86_64'
  local tools="$ANDROID_HOME/cmdline-tools/latest/bin"
  sudo chmod a+rw /dev/kvm
  "$tools/sdkmanager" emulator "$image" 'platforms;android-35' 'build-tools;35.0.0'
  export PATH="$ANDROID_HOME/platform-tools:$PATH"
  echo "$ANDROID_HOME/platform-tools" >> "$GITHUB_PATH"
  export ANDROID_USER_HOME="$HOME/.android"
  export ANDROID_AVD_HOME="$RUNNER_TEMP/$name-avds"
  mkdir -p "$ANDROID_USER_HOME" "$ANDROID_AVD_HOME"
  adb start-server
  echo no | "$tools/avdmanager" create avd --force --name "$name" --package "$image" --path "$ANDROID_AVD_HOME/$name.avd"
  "$ANDROID_HOME/emulator/emulator" -list-avds | grep -Fx "$name"
  "$ANDROID_HOME/emulator/emulator" -avd "$name" -port 5554 -no-window -no-audio \
    -no-snapshot -no-boot-anim -gpu swiftshader_indirect > "$log" 2>&1 &
  local pid=$!
  if ! timeout 360 bash -c 'until [[ "$(adb -s emulator-5554 shell getprop sys.boot_completed 2>/dev/null | tr -d "\r")" == 1 ]]; do kill -0 "$1" || exit 1; sleep 2; done' bash "$pid"; then
    tail -100 "$log"
    return 1
  fi
  adb -s emulator-5554 shell input keyevent KEYCODE_WAKEUP
  adb -s emulator-5554 shell wm dismiss-keyguard
}
