#!/usr/bin/env bash
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
serial=$1
proof=$2
sdk=${ANDROID_HOME:?Android SDK location required}
tools="$sdk/build-tools/35.0.0"
platform="$sdk/platforms/android-35/android.jar"
ndk=${ANDROID_NDK_HOME:-"$sdk/ndk/27.2.12479018"}
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$work/classes" "$work/lib"
abi=$(adb -s "$serial" shell getprop ro.product.cpu.abi | tr -d '\r')
case "$abi" in
    x86_64) compiler=x86_64-linux-android30-clang ;;
    arm64-v8a) compiler=aarch64-linux-android30-clang ;;
    *) echo "Unsupported fixture ABI $abi" >&2; exit 1 ;;
esac
mkdir -p "$work/lib/$abi"
"$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/$compiler" -Wall -Wextra -Werror \
    -shared "$here/native.c" -o "$work/lib/$abi/libstartupfixture.so"
javac --release 8 -cp "$platform" -d "$work/classes" "$here/StartupActivity.java"
"$tools/d8" --lib "$platform" --min-api 30 --output "$work" "$work/classes/dev/uitest/startup/StartupActivity.class"
"$tools/aapt" package -f -M "$here/AndroidManifest.xml" -I "$platform" -F "$work/raw.apk"
(cd "$work" && "$tools/aapt" add raw.apk classes.dex "lib/$abi/libstartupfixture.so")
"$tools/zipalign" -f 4 "$work/raw.apk" "$work/aligned.apk"
keytool -genkeypair -alias fixture -keystore "$work/signing.jks" -storepass fixture123 \
    -keypass fixture123 -keyalg RSA -keysize 2048 -validity 2 -dname 'CN=Startup Fixture'
"$tools/apksigner" sign --ks "$work/signing.jks" --ks-pass pass:fixture123 --out "$work/fixture.apk" "$work/aligned.apk"
mkdir -p "$proof"
adb -s "$serial" shell 'getprop ro.build.version.sdk; getprop ro.product.cpu.abilist; getprop ro.boot.verifiedbootstate' > "$proof/device.txt"
adb -s "$serial" install -r "$work/fixture.apk"
for mode in normal finish java native exit; do
    bash "$here/capture.sh" "$serial" dev.uitest.startup dev.uitest.startup/.StartupActivity "$proof/$mode" --es mode "$mode"
done
for mode in normal finish java native exit; do
    diff -u "$proof/$mode/exit-before.txt" "$proof/$mode/exit-after.txt" > "$proof/$mode/exit.diff" || [ "$?" = 1 ]
done
test -s "$proof/normal/pid-10.txt"
test -s "$proof/finish/pid-10.txt"
test ! -s "$proof/java/pid-10.txt"
test ! -s "$proof/native/pid-10.txt"
test ! -s "$proof/exit/pid-10.txt"
grep -Eq '^\+.*reason=4 \(APP CRASH\(EXCEPTION\)\)' "$proof/java/exit.diff"
grep -Eq '^\+.*reason=5 \(APP CRASH\(NATIVE\)\)' "$proof/native/exit.diff"
grep -Eq '^\+.*reason=1 \(EXIT_SELF\).*status=23' "$proof/exit/exit.diff"
grep -q 'StartupFixture synthetic Java failure' "$proof/java/logcat.txt"
grep -q 'SIGABRT' "$proof/native/logcat.txt"
grep -q 'mode=finish' "$proof/finish/logcat.txt"
printf '%s\n' 'normal and finish persisted; Java, native, and explicit exit classified' > "$proof/result.txt"
