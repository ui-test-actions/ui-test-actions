"""Send native pointer, keyboard, and window commands from an external client."""

import argparse
import json
from pathlib import Path
import time

from probe_fixture import Client, screenshot
from fixtures.desktop_interactions import ANCHOR, HEIGHT, TEXT, WIDTH


def wait_for_window(client, title):
    for _ in range(12):
        windows = client.command("windows.list", {})["result"]["windows"]
        match = [window for window in windows if window["title"] == title]
        if match:
            return match[0]
        time.sleep(.25)
    raise AssertionError(f"Window did not appear: {title}")


def find_origin(frame):
    expected = tuple(bytes.fromhex(ANCHOR[1:]))
    for y in range(min(260, frame.height)):
        for x in range(min(360, frame.width)):
            actual = frame.getpixel((x, y))
            if max(abs(channel - target) for channel, target in zip(actual, expected)) <= 4:
                return x, y
    raise AssertionError("The fixture's visible coordinate marker was not found.")


def run(client, evidence):
    session = client.identify()
    before = screenshot(client)
    x, y = find_origin(before)
    crop = (x, y, x + WIDTH, y + HEIGHT)
    before.crop(crop).save(evidence / "before.png")

    def point(px, py):
        return {"x": x + px, "y": y + py}

    client.command("pointer.click", point(322, 170))
    client.command("pointer.move", point(155, 175) | {"duration_ms": 250})
    client.command("pointer.move", point(244, 50) | {"duration_ms": 300})
    client.command("pointer.click", point(394, 51) | {"count": 2})
    client.command("pointer.click", point(84, 132) | {"hold_ms": 750})
    client.command("pointer.drag", point(86, 53) | {"end_x": x + 240, "end_y": y + 132, "duration_ms": 650})
    client.command("pointer.scroll", point(458, 128) | {"dy": 3})
    client.command("pointer.click", point(500, 50) | {"button": "right"})
    time.sleep(.4)
    screenshot(client).save(evidence / "context.png")
    client.command("pointer.click", point(538, 60))
    client.command("keyboard.press", {"keys": ["escape"]})
    client.command("pointer.click", point(155, 245))
    client.command("text.insert", {"text": TEXT})
    client.command("keyboard.press", {"keys": ["f6"]})
    client.command("pointer.click", point(87, 374))
    main = wait_for_window(client, "Native interaction fixture")
    detail = wait_for_window(client, "Native interaction detail")
    detail_id = {"id": detail["id"]}
    client.command("windows.focus", {"id": main["id"]})
    client.command("windows.move_resize", detail_id | {"x": 690, "y": 230, "width": 280, "height": 195})
    client.command("windows.focus", detail_id)
    time.sleep(.5)
    resized = wait_for_window(client, "Native interaction detail")
    if detail["bounds"] == resized["bounds"]:
        raise AssertionError("The detail window bounds did not change.")
    screenshot(client).save(evidence / "detail.png")
    client.command("windows.close", detail_id)
    for _ in range(12):
        remaining = client.command("windows.list", {})["result"]["windows"]
        if not any(window["id"] == detail["id"] for window in remaining):
            break
        time.sleep(.25)
    else:
        raise AssertionError("The detail window stayed open.")

    screenshot(client).crop(crop).save(evidence / "after.png")
    result = {"target": session["target"], "detail_before": detail["bounds"],
              "detail_after": resized["bounds"], "window_closed": True}
    (evidence / "client.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    session = Client(json.loads(args.connection.read_text(encoding="utf-8")), args.token_file)
    print(json.dumps(run(session, args.evidence), indent=2))
