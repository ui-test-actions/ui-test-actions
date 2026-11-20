#!/usr/bin/env bash
set -euo pipefail

dir="$RUNNER_TEMP/mobile-lan"
evidence="$RUNNER_TEMP/mobile-lan-preflight"
src=verification/mobile-lan
stage="${1:?}"
target="${2:?}"
mkdir -p "$dir" "$evidence"

case "$stage" in
  identity)
    umask 077
    mkdir -p "$dir/public"
    openssl req -x509 -newkey ed25519 -nodes -days 1 -subj /CN=ui-mobile-lan \
      -addext subjectAltName=DNS:ui-mobile-lan -keyout "$dir/key.pem" -out "$dir/public/cert.pem"
    cc -O2 -Wall -Wextra -Werror "$src/frame-port.c" -o "$dir/frame-port"
    python3 -m venv "$dir/venv"
    "$dir/venv/bin/pip" install --disable-pip-version-check 'websockets==15.0.1'
    ;;
  rendezvous)
    if [[ "$target" == android ]]; then
      "$dir/venv/bin/python" "$src/open-tunnel.py" "$dir/tunnel" "$dir/public/origin" > "$evidence/tunnel-supervisor.log" 2>&1 &
      echo "$!" > "$dir/tunnel.pid"
      for _ in {1..110}; do
        if [[ -s "$dir/public/origin" ]]; then exit 0; fi
        kill -0 "$(cat "$dir/tunnel.pid")"
        sleep 1
      done
      exit 1
    fi
    ;;
  bridge)
    peer=ios
    role=server
    interface=uilan0
    if [[ "$target" == ios ]]; then
      peer=android
      role=client
      interface=feth81
    fi
    for _ in {1..80}; do
      gh run download "$GITHUB_RUN_ID" --repo "$GITHUB_REPOSITORY" --name "lan-$peer-$GITHUB_RUN_ATTEMPT" --dir "$dir/peer" >/dev/null 2>&1 || true
      if [[ -s "$dir/peer/cert.pem" ]]; then break; fi
      sleep 3
    done
    test -s "$dir/peer/cert.pem"
    if [[ "$role" == client ]]; then
      origin=(--origin "$(cat "$dir/peer/origin")")
    else
      origin=()
    fi
    # The privileged helper sees only the dedicated job-local interface.
    sudo -n "$dir/venv/bin/python" "$src/bridge.py" "$role" --interface "$interface" --frame-port "$dir/frame-port" \
      --cert "$dir/public/cert.pem" --key "$dir/key.pem" --peer-cert "$dir/peer/cert.pem" \
      --ready "$dir/ready" ${origin[@]+"${origin[@]}"} > "$evidence/bridge.log" 2>&1 &
    echo "$!" > "$dir/bridge.pid"
    for _ in {1..220}; do
      if [[ -f "$dir/ready" ]]; then exit 0; fi
      kill -0 "$(cat "$dir/bridge.pid")" || { cat "$evidence/bridge.log"; exit 1; }
      sleep 1
    done
    exit 1
    ;;
  verify)
    if [[ "$target" == android ]]; then
      adb -s emulator-5554 shell ping -c 3 -W 4 192.168.137.2 | tee "$evidence/android-to-mac.txt"
    else
      ping -c 3 -W 4000 192.168.137.10 | tee "$evidence/mac-to-android.txt"
    fi
    # Give the other job time to perform its check.
    sleep 30
    ;;
  cleanup)
    for name in bridge tunnel; do
      if [[ -s "$dir/$name.pid" ]]; then sudo kill "$(cat "$dir/$name.pid")" 2>/dev/null || true; fi
    done
    if [[ "$target" == android ]]; then
      adb -s emulator-5554 emu kill || true
      if [[ -s "$evidence/dnsmasq.pid" ]]; then sudo kill "$(cat "$evidence/dnsmasq.pid")" 2>/dev/null || true; fi
      sudo ip link del uilan0 2>/dev/null || true
    else
      sudo ifconfig feth80 destroy || true
      sudo ifconfig feth81 destroy || true
      if [[ -s "$evidence/device" ]]; then xcrun simctl shutdown "$(cat "$evidence/device")" || true; fi
    fi
    rm -f "$dir/key.pem"
    ;;
  *) exit 2 ;;
esac
