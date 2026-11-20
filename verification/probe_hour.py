"""Drive the Linux hosted fixture near both ends of a 60-minute session."""

import argparse
from datetime import datetime, timezone
from http.client import HTTPException, HTTPSConnection
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from PIL import ImageChops

from probe_fixture import Client, exercise, screenshot


ENTRY = (320, 200)
APPLY = (341, 267)
WINDOW = (59, 59, 623, 438)
STATUS = (85, 104, 599, 160)
LATE_TEXT = "Late-hour v2 — قبل انتهاء الساعة ١٢٣"


def wait_until(when):
    while (remaining := when - time.time()) > 0:
        time.sleep(min(60, remaining))


def record(directory, **event):
    observed = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with (directory / "observations.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"observed_at": observed, **event}) + "\n")


def authenticate_at_expiry(client, expires_at, evidence):
    address = urlsplit(client.origin)
    for offset in (-8, 1, 6, 15):
        wait_until(expires_at + offset)
        connection = HTTPSConnection(address.hostname, timeout=5)
        try:
            connection.request("GET", "/v1/session", headers=client.headers)
            response = connection.getresponse()
            status = response.status
            response.read()
        except (OSError, HTTPException):
            status = "unreachable"
        finally:
            connection.close()
        record(evidence, seconds_relative_to_expiry=round(time.time() - expires_at, 2), authenticated_status=status)
        if offset >= 6 and status not in (404, 410, 502, 503, 504, 530, "unreachable"):
            raise AssertionError(f"The session still responds after expiry with HTTP {status}.")


def run(connection, token_file, evidence, resume):
    client = Client(connection, token_file)
    first = client.identify()
    expires_at = connection["expires_unix"]
    expiration = datetime.fromtimestamp(expires_at, timezone.utc).isoformat()
    trace = evidence / "observations.jsonl"
    if first["target"] != "linux":
        raise ValueError("Use the hosted Linux fixture.")
    if resume:
        previous = json.loads(trace.read_text(encoding="utf-8").splitlines()[0])
        if previous["expires_at"] != expiration or not (evidence / "result.json").is_file():
            raise ValueError("Resume using the same connection and its existing early evidence.")
    else:
        if trace.exists() or not 3400 <= first["seconds_remaining"] <= 3600:
            raise ValueError("Use a new evidence directory and a fresh 60-minute Linux session.")
        record(evidence, seconds_remaining=first["seconds_remaining"], same_session=True, expires_at=expiration)
        exercise(connection, token_file, evidence, ENTRY, APPLY, (100, 120), WINDOW, None)
        print("Early fixture transition verified.", flush=True)
    for remaining in (3000, 2400, 1800, 1200, 600, 300, 120, 60):
        if time.time() >= expires_at - remaining:
            continue
        wait_until(expires_at - remaining)
        observed = Client(connection, token_file).identify()
        if observed["id"] != first["id"]:
            raise AssertionError("The fresh client connected to a different session.")
        record(evidence, seconds_remaining=observed["seconds_remaining"], same_session=True)
    wait_until(expires_at - 45)

    before = screenshot(client)
    actions = [
        {"command": "pointer.click", "params": dict(zip(("x", "y"), ENTRY))},
        {"command": "keyboard.press", "params": {"keys": ["home"]}},
        {"command": "keyboard.press", "params": {"keys": ["shift", "end"]}},
        {"command": "keyboard.press", "params": {"keys": ["backspace"]}},
        {"command": "text.insert", "params": {"text": LATE_TEXT}},
        {"command": "pointer.click", "params": dict(zip(("x", "y"), APPLY))},
    ]
    result = client.batch(actions)
    time.sleep(.5)
    after = screenshot(client)
    difference = ImageChops.difference(before.crop(STATUS), after.crop(STATUS)).getbbox()
    for label, frame in (("late-before", before), ("late-after", after)):
        frame.crop(WINDOW).save(evidence / (label + ".png"))
    if not result["ok"] or difference is None:
        raise AssertionError("The late fixture status label did not change.")
    client.command("pointer.click", dict(zip(("x", "y"), ENTRY)))
    client.command("keyboard.press", {"keys": ["home"]})
    client.command("keyboard.press", {"keys": ["shift", "end"]})
    client.command("clipboard.set", {"text": "copy-back sentinel"})
    client.command("keyboard.press", {"keys": ["ctrl", "c"]})
    if client.command("clipboard.get", {})["result"]["text"] != LATE_TEXT:
        raise AssertionError("The late text did not survive an exact clipboard copy-back.")
    record(evidence, seconds_remaining=client.identify()["seconds_remaining"], late_batch_steps=result["completed"],
           exact_copyback=True, label_difference_bounds=difference, same_session=True)
    print("Late fixture transition and copy-back verified.", flush=True)
    authenticate_at_expiry(client, expires_at, evidence)
    print("External expiry verified.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()
    arguments.evidence.mkdir(parents=True, exist_ok=True)
    run(json.loads(arguments.connection.read_text(encoding="utf-8")), arguments.token_file,
        arguments.evidence, arguments.resume)
