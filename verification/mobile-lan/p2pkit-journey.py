"""Drive the pinned P2pKit sample pair through native discovery and chat."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent import Client, ClientError


def ios_received_message(line, android_name, payload, *, visual):
    if line == f"{android_name} -> {payload}":
        return True
    if visual:
        # The sample's random numeric name suffix was already verified on the
        # discovery screen. OCR can misread the tiny Android prefix in chat.
        match = re.fullmatch(r"[A-Za-z]+-(\d{1,4}) -> (.+)", line)
        return bool(match and android_name == f"Android-{match[1]}" and match[2] == payload)
    return False


class Device:
    def __init__(self, target, connection, token, output):
        self.target = target
        self.client = Client(json.loads(connection.read_text(encoding="utf-8")), token)
        session = self.client.identify()
        if session["target"] != target:
            raise RuntimeError(f"Expected the {target} connection")
        self.output = output
        self.screen_size = None
        self.ocr = None
        self.crop = None
        self.start_point = None

    def command(self, name, params):
        result = self.client.command(name, params)
        if not result["ok"]:
            raise RuntimeError(f"{self.target} rejected {name}")
        return result["result"]

    def screenshot(self, label=None):
        image = self.client.fetch("/v1/screenshot")
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Expected a PNG screenshot")
        self.screen_size = struct.unpack("!II", image[16:24])
        if label:
            (self.output / f"{self.target}-{label}.png").write_bytes(image)
        return image

    def snapshot(self):
        if not self.ocr:
            return self.command("tree.snapshot", {})
        from visual_labels import read

        return {"snapshot_id": None, "nodes": [
            {"text": item["label"], "visible": True, "center": item["center"]}
            for item in read(self.screenshot(), self.ocr, self.crop)]}

    def find(self, predicate, label, *, scroll=0, timeout=35):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            tree = self.snapshot()
            matches = [node for node in tree["nodes"] if node["visible"] and predicate(node)]
            if matches:
                return tree["snapshot_id"], matches[0]
            if scroll:
                self.drag(scroll)
            time.sleep(.6)
        raise RuntimeError(f"{self.target} did not show {label}")

    def drag(self, direction):
        if not self.screen_size:
            self.screenshot()
        width, height = self.screen_size
        # The Android sample has nested peer and timeline scrollers. The
        # outside gutter belongs to the enclosing Room scroll view.
        x = max(1, width // 26)
        start, end = (height * 7 // 8, height // 4) if direction > 0 else (height // 4, height * 7 // 8)
        if self.crop:
            left, top, right, bottom = self.crop
            x = left + (right - left) * 3 // 4
            shallow, deep = top + (bottom - top) // 2, bottom - (bottom - top) // 6
            start, end = (deep, shallow) if direction > 0 else (shallow, deep)
        self.command("pointer.drag", {"x": x, "y": start, "end_x": x, "end_y": end, "duration_ms": 450})
        time.sleep(1 if self.ocr else .6)

    def click(self, predicate, label, *, scroll=0):
        for attempt in range(3):
            snapshot, node = self.find(predicate, label, scroll=scroll)
            try:
                if self.ocr:
                    self.command("pointer.click", dict(zip(("x", "y"), node["center"])))
                else:
                    self.command("element.click", {"snapshot_id": snapshot, "id": node["id"]})
                return
            except ClientError as error:
                if error.status != 409 or attempt == 2:
                    raise

    @staticmethod
    def content(node):
        return (node.get("name", ""), node.get("text", ""), node.get("resource_id", ""))

    def text(self, value, *, scroll=0, substring=False):
        selectors = ((lambda node: any(value in field for field in self.content(node))) if substring
                     else (lambda node: value in self.content(node)))
        self.find(selectors, repr(value), scroll=scroll)

    def button(self, label, *, scroll=0, starts=False):
        def matches(node):
            values = self.content(node)
            return any(v.startswith(label) for v in values) if starts else label in values

        def eligible(node):
            return node.get("enabled", True) and matches(node)

        self.click(eligible, repr(label), scroll=scroll)

    def message(self, value):
        if self.ocr:
            def is_send(node):
                return node["text"].startswith("Send all (")

            _, button = self.find(is_send, "visible iOS message composer", scroll=1)
            if button["center"][1] < self.crop[1] + 42:
                self.drag(-1)
                _, button = self.find(is_send, "iOS composer below the status bar")
            x, y = button["center"]
            self.command("pointer.click", {"x": x - (self.crop[2] - self.crop[0]) // 2, "y": y})
            time.sleep(.6)
            self.command("text.insert", {"text": value, "replace": True})
            self.button("Send all (", starts=True)
            return

        if self.target == "android":
            # Compose nests the label in its edit node and exposes unlabeled
            # text boxes for the nearby hotspot form.
            snapshot, label = self.find(lambda node: node.get("role") == "text" and node.get("text") == "Message",
                                        "Android message label", scroll=1)
            self.command("element.click", {"snapshot_id": snapshot, "id": label["parent_id"]})
            self.find(lambda node: node.get("role") == "textbox" and node["properties"].get("focused"),
                      "focused Android composer")
        else:
            self.click(lambda node: node.get("role") in ("AXTextField", "textbox") and any(
                field.lower() == "message" for field in self.content(node)), "iOS message editor", scroll=1)
        time.sleep(.6)
        self.command("text.insert", {"text": value, "replace": True})
        if self.target == "android":
            self.find(lambda node: node.get("role") == "textbox" and node.get("text") == value, "message draft")
            _, send = self.find(lambda node: node.get("enabled") and node.get("text") == "Broadcast (1)",
                                "enabled broadcast button")
            bounds = send["bounds"]
            self.command("pointer.click", {"x": bounds["x"] + bounds["width"] // 2,
                                           "y": bounds["y"] + bounds["height"] // 2})
            self.find(lambda node: node.get("role") == "text" and value in node.get("text", ""),
                      "sent message in the Android timeline")
        else:
            self.button("Send all (", starts=True)

    def start(self):
        marker = "state: Running" if self.target == "android" else "Status: Running" if self.ocr else "stop-kit"
        tree = self.snapshot()
        if not any(marker in self.content(node) for node in tree["nodes"]):
            if self.start_point:
                self.command("pointer.click", dict(zip(("x", "y"), self.start_point)))
            else:
                self.button("Start", scroll=1)
        if self.target == "ios" and not self.ocr:
            self.text(marker)
        else:
            self.text(marker, scroll=-1 if self.target == "android" else 0)


def exercise_link(android, ios, android_name, ios_name, output):
    evidence = {"profiles": []}

    def profile(command, params):
        result = android.command(f"network.profile.{command}", params)
        evidence["profiles"].append({"epoch": time.time(), **result})
        return result

    def readiness():
        return [device.client.identify()["target"] for device in (android, ios)]

    def from_ios(message):
        return f"{ios_name} → {message}"

    def has_line(node, line):
        return any(field == line or field.endswith(" " + line) for field in android.content(node))

    try:
        profile("get", {})
        profile("set", {"delay_ms": 500, "jitter_ms": 25, "rate_kbit": 512, "seconds": 40})
        ios.message("SLOW")
        android.find(lambda node: has_line(node, from_ios("SLOW")), "message over the slow link", scroll=-1)
        android.screenshot("slow-message")
        evidence["slow_receiver_line"] = from_ios("SLOW")
        # Independent native pings sample the active profile throughout the job.
        time.sleep(9)
        profile("set", {"loss_percent": 25, "seed": 123, "seconds": 25})
        time.sleep(14)
        offline = profile("set", {"offline": True, "seconds": 36})
        evidence["reachable_during_outage"] = readiness()
        ios.message("DROPOUT")
        evidence["outage_samples"] = []
        for _ in range(4):
            status = android.command("network.profile.get", {})
            if status["generation"] != offline["generation"] or not status["profile"]["offline"]:
                raise RuntimeError("The simulated outage expired before the receiver could be checked")
            nodes = android.snapshot()["nodes"]
            if not any(has_line(node, from_ios("SLOW")) for node in nodes):
                raise RuntimeError("The receiver observation does not include the previously verified timeline")
            if any(has_line(node, from_ios("DROPOUT")) for node in nodes):
                raise RuntimeError("The receiver displayed the new message during the simulated outage")
            evidence["outage_samples"].append(time.time())
            time.sleep(1)
        android.screenshot("offline-receiver")
        ios.screenshot("offline-sender")

        deadline = time.monotonic() + 42
        while time.monotonic() < deadline:
            state = android.command("network.profile.get", {})
            if not state["profile"]["offline"] and state["generation"] > offline["generation"]:
                profile("get", {})
                break
            time.sleep(1)
        else:
            raise RuntimeError("The traffic profile did not expire on schedule")

        ios.message("LINK UP")
        android.find(lambda node: has_line(node, from_ios("LINK UP")), "fresh iOS message after recovery", scroll=-1)
        android.screenshot("recovered-ios-message")
        android.message("REOPEN")
        _, message = ios.find(lambda node: any(ios_received_message(
            field, android_name, "REOPEN", visual=bool(ios.ocr)) for field in ios.content(node)),
            "fresh Android message after recovery", scroll=1)
        ios.screenshot("recovered-android-message")
        evidence["recovered_receiver_lines"] = {"android": from_ios("LINK UP"),
            "ios": next(field for field in ios.content(message)
                        if ios_received_message(field, android_name, "REOPEN", visual=bool(ios.ocr)))}
    finally:
        (output / "network.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        android.command("network.profile.reset", {})


def run_pair(android, ios, android_name, ios_name, nonce, initiator, output, network_faults=False):
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(android.screenshot, "before")
        second = pool.submit(ios.screenshot, "before")
        first.result()
        second.result()
        first = pool.submit(android.start)
        second = pool.submit(ios.start)
        first.result()
        second.result()
        print("Started both native LAN apps", flush=True)

        first = pool.submit(android.text, ios_name)
        second = pool.submit(ios.text, android_name)
        first.result()
        second.result()
        android.screenshot("discovered")
        ios.screenshot("discovered")
        print("Each app rendered the other app's discovery name", flush=True)

        (ios if initiator == "ios" else android).button("Connect", scroll=1)
        first = pool.submit(android.text, "Connected")
        second = (pool.submit(ios.text, "Sessions (1, 1 connected)")
                  if ios.ocr else pool.submit(ios.find, lambda node: any(
                      android_name in field and "Connected" in field for field in ios.content(node)),
                      "connected Android session", scroll=1))
        first.result()
        second.result()
        android.screenshot("connected")
        ios.screenshot("connected")
        print(f"Both apps reported Connected after {initiator} selected the discovered peer", flush=True)

        # A short unique payload is legible in the Simulator's compact message row.
        from_android = nonce
        from_ios = f"iOS reply {nonce}"
        android.message(from_android)
        def received_on_ios(field):
            return ios_received_message(field, android_name, from_android, visual=bool(ios.ocr))

        _, ios_message = ios.find(lambda node: any(received_on_ios(field) for field in ios.content(node)),
            "the Android sender and message in the iOS timeline", scroll=1)
        ios.screenshot("received-android")
        ios.message(from_ios)
        android_received = f"{ios_name} → {from_ios}"
        _, android_message = android.find(lambda node: any(android_received in field for field in android.content(node)),
            "the iOS sender and message in the Android timeline", scroll=-1)
        android.screenshot("received-ios")

    result = {"native_discovery": {"android_observed": ios_name, "ios_observed": android_name},
              "initiator": initiator, "connected_on_both": True,
              "observed_receiver_lines": {
                  "android": next(field for field in android.content(android_message) if android_received in field),
                  "ios": next(field for field in ios.content(ios_message) if received_on_ios(field)),
              }}
    (output / "journey.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if network_faults:
        exercise_link(android, ios, android_name, ios_name, output)
        print("Real sample traffic was delayed, interrupted, and exchanged again after lease expiry", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for target in ("android", "ios"):
        parser.add_argument(f"--{target}-connection", required=True, type=Path)
        parser.add_argument(f"--{target}-token", required=True, type=Path)
        parser.add_argument(f"--{target}-name", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--initiator", choices=("android", "ios"), default="ios")
    parser.add_argument("--ios-ocr", type=Path)
    parser.add_argument("--ios-crop", type=int, nargs=4)
    parser.add_argument("--ios-start", type=int, nargs=2)
    parser.add_argument("--network-faults", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    android = Device("android", args.android_connection, args.android_token, args.output)
    ios = Device("ios", args.ios_connection, args.ios_token, args.output)
    if args.ios_ocr:
        if not args.ios_crop or not args.ios_start:
            parser.error("--ios-ocr requires --ios-crop and --ios-start measured from the current Simulator screenshot")
        ios.ocr, ios.crop = args.ios_ocr, args.ios_crop
    ios.start_point = args.ios_start
    run_pair(android, ios, args.android_name, args.ios_name, args.nonce, args.initiator, args.output, args.network_faults)


if __name__ == "__main__":
    main()
