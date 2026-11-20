"""Verify actual Android runtime classification and relaunch of the isolated fixture."""

import argparse
import json
from pathlib import Path
from struct import unpack
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Client, ClientError

APP = "dev.uitest.fixture"


def until(observe, label, seconds=32):
    expires = time.monotonic() + seconds
    while time.monotonic() < expires:
        try:
            if value := observe():
                return value
        except ClientError as error:
            if error.status not in (408, 429, 502, 504):
                raise
        time.sleep(.55)
    raise RuntimeError(f"Android did not show {label}.")


def run(client, output):
    assert client.identify()["target"] == "android"
    output.mkdir(mode=0o700)

    def command(name, params=None):
        return client.command(name, params or {})["result"]

    def screenshot(name):
        image = client.fetch("/v1/screenshot")
        (output / (name + ".png")).write_bytes(image)
        return unpack(">II", image[16:24])

    def sample():
        return command("app.metrics", {"id": APP})

    def exit_reason(code, reason):
        def observe():
            process = sample()
            if not process["running"] and process.get("last_os_exit") == {"reason_code": code, "reason": reason}:
                return process

        return until(observe, reason)

    def node(selector):
        result = command("element.find", {"selector": {"visible": True, **selector}})
        return result if result["matched"] == 1 else None

    def close_dialog(result):
        command("element.click", {"id": result["nodes"][0]["id"], "snapshot_id": result["snapshot_id"]})

    baseline = sample()
    assert baseline["running"]
    width, height = screenshot("before")
    command("app.deeplink", {"url": "ui-test-fixture://fail-crash"})
    crash = exit_reason(4, "CRASH")
    screenshot("after-crash")
    print("Android issued a native Java CRASH reason", flush=True)
    command("app.launch", {"id": APP})
    until(lambda: node({"text_contains": "Ready for input"}), "a usable app after its crash")
    restarted = sample()
    assert restarted["running"] and restarted["pid"] != baseline["pid"]
    screenshot("crash-recovered")
    command("app.deeplink", {"url": "ui-test-fixture://fail-anr"})
    time.sleep(3)
    try:
        command("pointer.click", {"x": width // 2, "y": height // 3})
    except ClientError as error:
        if error.status not in (408, 502, 504):
            raise
    close = until(lambda: node({"text": "Close app"}), "the native application-not-responding dialog", 38)
    screenshot("anr-dialog")
    close_dialog(close)
    anr = exit_reason(6, "ANR")
    print("Android issued a native ANR reason after the OS dialog closed the unresponsive app", flush=True)
    command("app.launch", {"id": APP})
    until(lambda: node({"text_contains": "Ready for input"}), "a usable app after its ANR")
    recovered = sample()
    assert recovered["running"] and recovered["pid"] != restarted["pid"]
    screenshot("anr-recovered")
    (output / "outcomes.json").write_text(json.dumps({
        "baseline": baseline, "crash": crash, "crash_recovery": restarted,
        "anr": anr, "anr_recovery": recovered,
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(Client(json.loads(args.connection.read_text()), args.token_file), args.output)
