#!/usr/bin/env bash
set -euo pipefail
src=$(cd "$(dirname "$0")" && pwd)
output="${1:?provide an output directory}"
sdk="${ANDROID_HOME:?ANDROID_HOME must point to the SDK}"
tools="$sdk/build-tools/35.0.0"
platform="$sdk/platforms/android-35/android.jar"
mkdir -p "$output/classes" "$output/dex"
javac --release 8 -encoding UTF-8 -classpath "$platform" -d "$output/classes" "$src/MainActivity.java"
"$tools/d8" --lib "$platform" --min-api 26 --output "$output/dex" "$output/classes/dev/uitest/fixture/MainActivity.class"
"$tools/aapt" package -f -M "$src/AndroidManifest.xml" -I "$platform" -F "$output/fixture.apk"
apk=$(cd "$output" && pwd)/fixture.apk
(cd "$output/dex" && "$tools/aapt" add "$apk" classes.dex)
keytool -genkeypair -noprompt -keystore "$output/fixture.jks" -storepass android -keypass android \
  -alias fixture -keyalg RSA -keysize 2048 -validity 3650 -dname "CN=Test fixture"
"$tools/apksigner" sign --ks "$output/fixture.jks" --ks-pass pass:android "$apk"
