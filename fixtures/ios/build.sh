#!/usr/bin/env bash
set -euo pipefail
src=$(cd "$(dirname "$0")" && pwd)
app="${1:?provide a .app output path}"
mkdir -p "$app"
cp "$src/Info.plist" "$app/Info.plist"
xcrun --sdk iphonesimulator swiftc -parse-as-library \
  -target "$(uname -m)-apple-ios17.0-simulator" -sdk "$(xcrun --sdk iphonesimulator --show-sdk-path)" \
  "$src/Fixture.swift" -o "$app/LiveUIFixture"
codesign --force --sign - "$app"
