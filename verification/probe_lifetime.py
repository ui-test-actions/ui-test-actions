"""Collect opening, near-expiry, and cancellation evidence from an external host."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.client import HTTPException, HTTPSConnection
import json
from pathlib import Path
import subprocess
import time
from typing import NamedTuple
from urllib.parse import urlsplit

from PIL import ImageChops

from probe_fixture import AFTER_COLOR, Client, exercise, require_color, screenshot


class Layout(NamedTuple):
    entry: tuple
    apply: tuple
    sample: tuple
    crop: tuple
    label: tuple
    dismiss: tuple | None = None


LAYOUTS = {
    "windows": Layout((320, 209), (347, 276), (100, 120), (60, 60, 642, 460), (85, 124, 610, 168)),
    "macos": Layout((320, 200), (340, 262), (100, 120), (60, 60, 620, 438), (85, 120, 605, 166)),
    "linux": Layout((320, 200), (341, 267), (100, 120), (60, 60, 623, 437), (85, 112, 605, 165)),
    "android": Layout((131, 145), (159, 192), (16, 40), (0, 0, 320, 640), (28, 87, 295, 133)),
    "ios": Layout((490, 207), (510, 249), (629, 300), (364, 25, 660, 697), (399, 156, 625, 188), (449, 323)),
}
IOS_MACOS_26 = Layout((491, 227), (511, 269), (629, 309), (361, 30, 661, 709), (399, 175, 625, 210), (449, 339))
TERMINAL = (410, 530)
RETRYABLE = (None, 502, 503, 504)


def utc(when=None):
    moment = datetime.now(timezone.utc) if when is None else datetime.fromtimestamp(when, timezone.utc)
    return moment.isoformat(timespec="milliseconds")


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def status(client, *, authenticated=True):
    origin = urlsplit(client.origin)
    start = time.time()
    connection = HTTPSConnection(origin.hostname, origin.port, timeout=4)
    try:
        connection.request("GET", "/v1/session", headers=client.headers if authenticated else {})
        response = connection.getresponse()
        code = response.status
        reply = response.read(65536)
    except (OSError, HTTPException):
        code, reply = None, b""
    finally:
        connection.close()
    received = time.time()
    result = {"at": utc(received), "http": code}
    if code == 200:
        session = json.loads(reply)
        if session["id"] != client.session_id:
            raise AssertionError("The endpoint returned another session.")
        result["seconds_remaining"] = session["seconds_remaining"]
        result["deadline_estimate"] = (start + received) / 2 + session["seconds_remaining"]
    return result


def checkpoint(client, evidence):
    with (evidence / "checkpoints.jsonl").open("a", encoding="utf-8") as output:
        for attempt in range(3):
            check = status(client)
            output.write(json.dumps(check) + "\n")
            if check["http"] == 200:
                return check
            if check["http"] not in RETRYABLE or attempt == 2:
                break
            time.sleep(1)
    raise AssertionError(f"Authenticated checkpoint failed: {check}")


def opening(connection, token_file, client, evidence, layout, *, hour):
    initial = checkpoint(client, evidence)
    if hour and not 3300 <= initial["seconds_remaining"] <= 3600:
        raise AssertionError("The hour proof needs an opening observation in the first five minutes.")
    result = exercise(connection, token_file, evidence, layout.entry, layout.apply, layout.sample, layout.crop,
                      layout.dismiss, fixture_text="Hour start" if hour else "Cancel check")
    result["first_authenticated"] = initial
    result["advertised_expiry"] = utc(connection["expires_unix"])
    save(evidence / "result.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def click(point):
    return {"command": "pointer.click", "params": {"x": point[0], "y": point[1]}}


def change_label(client, evidence, target, layout, text, prefix):
    before = screenshot(client)
    before.crop(layout.crop).save(evidence / f"{prefix}-before.png")
    require_color(before, layout.sample, AFTER_COLOR)
    steps = [click(layout.entry)]
    replace = target in ("android", "ios", "macos")
    if not replace:
        steps.extend({"command": "keyboard.press", "params": {"keys": keys}}
                     for keys in (["home"], ["shift", "end"], ["backspace"]))
    steps.extend([
        {"command": "text.insert", "params": {"text": text, "replace": replace}},
        click(layout.apply),
    ])
    result = client.batch(steps)
    if not result["ok"] or result["completed"] != len(steps):
        raise AssertionError(f"The late mutation did not complete: {result}")
    time.sleep(.4)
    after = screenshot(client)
    after.crop(layout.crop).save(evidence / f"{prefix}-after.png")
    require_color(after, layout.sample, AFTER_COLOR)
    difference = ImageChops.difference(before.crop(layout.label), after.crop(layout.label))
    box = difference.getbbox()
    if box is None or sum(pixel != (0, 0, 0) for pixel in difference.getdata()) < 50:
        raise AssertionError("The rendered app status did not visibly change.")
    return box


def late_change(client, evidence, target, layout):
    box = change_label(client, evidence, target, layout, "Hour end", "late")
    current = checkpoint(client, evidence)
    if not 0 < current["seconds_remaining"] <= 60:
        raise AssertionError(f"The mutation needs to finish inside the last minute: {current}")
    result = {"observed_at": current["at"], "seconds_remaining": current["seconds_remaining"],
              "expected_app_label": "AFTER · Hour end", "label_region": layout.label, "change_bounds": box}
    save(evidence / "late.json", result)
    print(json.dumps(result), flush=True)


def verify_expiry(client, evidence, deadline):
    samples = []
    while time.time() < deadline + 25:
        check = status(client)
        check["offset_seconds"] = round(time.time() - deadline, 2)
        samples.append(check)
        time.sleep(2)
    save(evidence / "expiry.json", samples)
    alive = [sample for sample in samples if sample["http"] == 200]
    denied = [sample for sample in samples if sample["offset_seconds"] > 5 and sample["http"] in TERMINAL]
    if not alive or alive[-1]["seconds_remaining"] > 15 or len(denied) < 2:
        raise AssertionError("Expected a live authenticated read within 15 seconds and repeated terminal responses.")
    if alive[-1]["offset_seconds"] > 5 or samples[-1]["http"] not in TERMINAL:
        raise AssertionError("Authenticated access remained available after the expiry tolerance.")
    print(json.dumps({"last_success": alive[-1], "after": denied[-1]}), flush=True)


def observe_expiry(client, evidence, target, layout):
    initial = checkpoint(client, evidence)
    while initial["seconds_remaining"] > 55:
        time.sleep(min(30, initial["seconds_remaining"] - 55))
        initial = checkpoint(client, evidence)
    with ThreadPoolExecutor(max_workers=1) as observer:
        trace = observer.submit(verify_expiry, client, evidence, initial["deadline_estimate"])
        late_change(client, evidence, target, layout)
        trace.result()


def cancel(client, evidence, run_id):
    if status(client)["http"] != 200:
        raise AssertionError("The cancellation experiment must start with an open authenticated endpoint.")
    requested = time.time()
    command = subprocess.Popen(["gh", "run", "cancel", str(run_id)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    samples = []
    while time.time() < requested + 50:
        check = status(client)
        check["seconds_from_submission"] = round(time.time() - requested, 3)
        samples.append(check)
        if len(samples) >= 2 and all(sample["http"] in TERMINAL for sample in samples[-2:]):
            break
        time.sleep(.9)
    _, error = command.communicate(timeout=10)
    if command.returncode:
        raise RuntimeError("GitHub rejected cancellation: " + error.decode(errors="replace").strip())
    first = next((sample for sample in samples if sample["http"] in TERMINAL), None)
    result = {"requested_at": utc(requested), "run_id": run_id, "first_terminal": first, "samples": samples}
    save(evidence / "cancellation.json", result)
    if first is None or not all(sample["http"] in TERMINAL for sample in samples[-2:]):
        raise AssertionError("GitHub cancellation did not produce two terminal observations.")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("open", "checkpoint", "expire", "cancel"))
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--ios-runner", choices=("macos-15", "macos-26"), default="macos-15",
                        help="Select the visible Simulator fixture geometry for the hosted image")
    args = parser.parse_args()
    connection = json.loads(args.connection.read_text(encoding="utf-8"))
    client = Client(connection, args.token_file)
    target = connection["target"]
    layout = IOS_MACOS_26 if target == "ios" and args.ios_runner == "macos-26" else LAYOUTS[target]
    args.evidence.mkdir(parents=True, exist_ok=True)
    if args.phase == "open":
        opening(connection, args.token_file, client, args.evidence, layout, hour=True)
    elif args.phase == "checkpoint":
        print(json.dumps(checkpoint(client, args.evidence)), flush=True)
    elif args.phase == "expire":
        observe_expiry(client, args.evidence, target, layout)
    else:
        if args.run_id is None:
            parser.error("--run-id is required to cancel")
        opening(connection, args.token_file, client, args.evidence, layout, hour=False)
        cancel(client, args.evidence, args.run_id)
