"""Verify the native app's visible response to environment changes."""

import argparse
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Client, ClientError


APP = "dev.uitest.fixture"
BLUE = (25, 43, 66)


def screenshot_app(frame):
    from PIL import Image, ImageChops

    image = Image.open(BytesIO(frame)).convert("RGB")
    diff = ImageChops.difference(image, Image.new("RGB", image.size, BLUE))
    red, green, blue = (channel.point(lambda value: 255 if value <= 1 else 0) for channel in diff.split())
    bounds = ImageChops.multiply(ImageChops.multiply(red, green), blue).getbbox()
    if not bounds:
        return image
    return image.crop(bounds)


def visible_labels(client, ocr=None):
    if ocr:
        image = screenshot_app(client.fetch("/v1/screenshot")).convert("L")
        data = BytesIO()
        image.resize((image.width * 3, image.height * 3)).save(data, "PNG")
        result = subprocess.run([str(ocr), "stdin", "stdout", "--psm", "11"], input=data.getvalue(),
                                capture_output=True, check=True, timeout=9)
        return [line.strip() for line in result.stdout.decode().splitlines() if line.strip()]
    tree = client.command("tree.snapshot", {})["result"]
    return [line for node in tree["nodes"] if node["visible"] for line in node.get("text", "").splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ocr", type=Path)
    parser.add_argument("--permission", choices=("camera", "photos", "microphone"))
    parser.add_argument("--request-photos", action="store_true",
                        help="Ask the fixture's Photos API to resolve authorization before app-level grant and denial checks")
    args = parser.parse_args()
    client = Client(json.loads(args.connection.read_text(encoding="utf-8")), args.token_file)
    target = client.identify()["target"]
    permission = args.permission or {"ios": "photos", "android": "camera"}[target]
    args.output.mkdir(exist_ok=True, parents=True)
    observations = []

    def command(name, params=None):
        response = client.command(name, params or {})
        if not response["ok"]:
            raise RuntimeError(f"Unexpected response for {name}")
        return response["result"]

    def assert_visible(label, *expected):
        route = "request-photos" if args.request_photos and permission == "photos" and label in {"granted", "denied"} else "environment"
        command("app.deeplink", {"url": f"ui-test-fixture://{route}"})
        deadline = time.monotonic() + 15
        while True:
            labels = visible_labels(client, args.ocr)
            if all(any(re.fullmatch(pattern, line, re.IGNORECASE) for line in labels) for pattern in expected):
                break
            if time.monotonic() >= deadline:
                (args.output / f"{label}-unmatched.txt").write_text("\n".join(labels), encoding="utf-8")
                raise RuntimeError(f"Observable environment did not match {label}")
            time.sleep(.4)
        frame = client.fetch("/v1/screenshot")
        if args.ocr:
            screenshot_app(frame).save(args.output / f"{label}.png")
        else:
            (args.output / f"{label}.png").write_bytes(frame)
        observations.append({"checkpoint": label, "labels": labels, "expected": expected})
        print(target, "observed", label, flush=True)

    def permission_state(state):
        command("app.permission.set", {"id": APP, "permission": permission, "state": state})
        # A privacy-state change can stop the app. Relaunch with the configured locale.
        command("app.launch" if target == "android" else "app.restart", {"id": APP})

    try:
        capabilities = command("app.environment.capabilities")
        if set(capabilities["apps"]) != {APP} or permission not in capabilities["apps"][APP]:
            raise RuntimeError("The exposed permissions did not match the workflow allowlist")
        try:
            command("app.permission.set", {"id": APP, "permission": "contacts", "state": "granted"})
        except ClientError as denied:
            if denied.status != 404:
                raise
        else:
            raise RuntimeError("The session accepted a permission outside its allowlist")
        command("app.locale.set", {"id": APP, "locale": ""})
        assert_visible("before", "LTR", "PORTRAIT")
        command("app.locale.set", {"id": APP, "locale": "ar-SA"})
        assert_visible("arabic", r"ar[- ]?SA", "RTL", "PORTRAIT")
        permission_state("granted")
        assert_visible("granted", "RTL", f"{permission} granted")
        permission_state("denied")
        assert_visible("denied", "RTL", f"{permission} denied")
        if target == "android":
            command("device.orientation", {"orientation": "landscape"})
        else:
            command("device.rotate", {"direction": "left"})
        time.sleep(2)
        assert_visible("landscape", "RTL", "LANDSCAPE")
        command("app.locale.set", {"id": APP, "locale": ""})
        if target == "ios":
            command("device.rotate", {"direction": "right"})
            time.sleep(1)
            permission_state("reset")
            assert_visible("restored", "LTR", "PORTRAIT", f"{permission} undetermined")
        else:
            command("device.orientation", {"orientation": "portrait"})
            time.sleep(1)
            assert_visible("restored", "LTR", "PORTRAIT", "Camera denied")
    finally:
        (args.output / "observations.json").write_text(json.dumps(observations, ensure_ascii=False, indent=2) + "\n",
                                                      encoding="utf-8")


if __name__ == "__main__":
    main()
