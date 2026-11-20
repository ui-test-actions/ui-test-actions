"""Drive the optional dashboard in Chromium against two authenticated hosted sessions."""

import argparse
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

from PIL import Image, ImageChops
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def frame(page, origin, headers, target, trigger):
    with page.expect_response(lambda response: response.url.endswith(f"/api/device/{target}/screenshot")
                              and response.status == 200) as capture:
        trigger()
    expect(page.locator("#screen")).to_be_visible()
    expect(page.locator("#dimensions")).to_have_text(re.compile(r"\d+ × \d+"))
    body = capture.value.body()
    if not body.startswith(b"\x89PNG\r\n\x1a\n"):
        direct = page.request.get(origin + f"/api/device/{target}/screenshot", headers=headers)
        assert direct.ok and direct.headers["content-type"] == "image/png"
        body = direct.body()
    return Image.open(BytesIO(body)).convert("RGB")


def viewport(image):
    delta = ImageChops.difference(image, Image.new("RGB", image.size, (25, 43, 66)))
    channels = [channel.point(lambda value: 255 if value == 0 else 0) for channel in delta.split()]
    bounds = ImageChops.multiply(ImageChops.multiply(*channels[:2]), channels[2]).getbbox()
    if not bounds or bounds[2] - bounds[0] != 560:
        raise RuntimeError("The fixture viewport was unavailable.")
    return bounds


def exercise(page, url, output):
    origin = url.split("/#", 1)[0]
    token = urlsplit(url).fragment.removeprefix("access=")
    headers = {"Authorization": "Bearer " + token}
    assert page.request.get(origin + "/api/devices").status == 401
    assert page.request.post(origin + "/api/device/linux/action", data={"command": "clipboard.get"},
                             headers={**headers, "Origin": "https://other.example"}).status == 403
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    expect(page.get_by_role("button", name="linux", exact=False)).to_be_enabled()
    expect(page.get_by_role("button", name="windows", exact=False)).to_be_enabled()
    before = frame(page, origin, headers, "linux", page.get_by_role("button", name="linux", exact=False).click)
    box = viewport(before)
    before.crop(box).save(output / "linux-before.png")
    page.locator("#touch").check()
    bounds = page.locator("#screen").bounding_box()
    x, y = (box[0] + box[2]) // 2, box[1] + 188
    after = frame(page, origin, headers, "linux", lambda: page.locator("#screen").click(
        position={"x": x * bounds["width"] / before.width, "y": y * bounds["height"] / before.height}))
    expect(page.locator("#result-title")).to_have_text("pointer.click")
    pixel = box[0] + 12, box[1] + 7
    if after.getpixel(pixel) != (23, 99, 59):
        raise RuntimeError("The live UI did not show the expected change.")
    after.crop(box).save(output / "linux-after.png")
    frame(page, origin, headers, "linux", page.get_by_role("button", name="Live preview").click)
    page.get_by_role("button", name="Live preview").click()

    replay = {"version": 1, "target": "linux", "steps": [{
        "expect": {"pixel": {"x": pixel[0], "y": pixel[1], "rgb": [23, 99, 59]}},
    }]}
    page.locator("#definition").fill(json.dumps(replay))
    page.locator("#run").click()
    expect(page.locator("#result-title")).to_have_text("Run · passed", timeout=12000)
    page.get_by_role("button", name="after.png").click()
    expect(page.locator("#evidence")).to_be_visible()
    page.screenshot(path=str(output / "dashboard.png"), full_page=True)
    replay["steps"][0]["expect"]["pixel"]["rgb"] = [250, 0, 250]
    replay["steps"][0]["expect"]["timeout_ms"] = 1200
    page.locator("#definition").fill(json.dumps(replay))
    page.locator("#run").click()
    expect(page.locator("#result-title")).to_have_text("Run · diverged", timeout=12000)
    page.get_by_role("button", name="failure.png").click()
    expect(page.locator("#evidence")).to_be_visible()

    finish(page, origin, headers, output, errors)


def finish(page, origin, headers, output, errors):
    windows = frame(page, origin, headers, "windows", page.get_by_role("button", name="windows", exact=False).click)
    expect(page.locator("#screen-title")).to_have_text("windows live screen")
    expect(page.get_by_role("button", name="Inspect tree")).to_be_enabled()
    with page.expect_response(lambda response: response.url.endswith("/api/device/windows/tree"), timeout=45000) as tree:
        page.get_by_role("button", name="Inspect tree").click()
    if tree.value.status != 200:
        raise RuntimeError(f"The Windows tree returned HTTP {tree.value.status}")
    expect(page.locator("#tree button").first).to_be_visible(timeout=12000)
    tree_count = page.locator("#tree button").count()
    windows.crop(viewport(windows)).save(output / "windows-live.png")
    page.locator("#command").select_option("recording.start")
    page.locator("#params").fill('{"duration_seconds":2}')
    page.locator("#execute").click()
    expect(page.locator("#result-title")).to_have_text("recording.start")
    page.wait_for_timeout(2500)
    page.locator("#command").select_option("recording.stop")
    page.locator("#execute").click()
    expect(page.locator('img[alt="Latest session recording"]')).to_be_visible(timeout=12000)
    result = page.request.get(origin + "/api/device/windows/recording", headers=headers)
    assert result.ok and result.body().startswith(b"GIF8")
    (output / "windows-session.gif").write_bytes(result.body())

    text = "مرحبًا ١٢٣ — Dashboard 🌍"
    stages = {"version": 1, "inputs": ["expected"], "stages": [{
        "name": "Set and check two live native clipboards",
        "devices": {name: {"workflow": {"version": 1, "inputs": ["expected"], "steps": [{
            "action": {"command": "clipboard.set", "params": {"text": {"input": "expected"}}},
        }]}, "capture": {f"{name}_clipboard": {"kind": "clipboard_text"}}} for name in ("linux", "windows")},
        "equal": [["linux_clipboard", "expected"], ["windows_clipboard", "expected"]],
    }]}
    page.locator("#mode").select_option("coordinate")
    page.locator("#definition").fill(json.dumps(stages, ensure_ascii=False))
    page.locator("#inputs").fill(json.dumps({"expected": text}, ensure_ascii=False))
    page.locator("#run").click()
    expect(page.locator("#result-title")).to_have_text("Run · passed", timeout=18000)
    page.reload()
    expect(page.locator("#history button")).to_have_count(3, timeout=12000)
    history = page.request.get(origin + "/api/history", headers=headers).json()["runs"]
    assert sorted(run["status"] for run in history) == ["diverged", "passed", "passed"]
    assert not errors, errors
    (output / "verified.json").write_text(json.dumps(
        {"targets": ["linux", "windows"], "windows_tree_nodes": tree_count, "cross_origin": 403,
         "anonymous": 401, "workflow_results": [run["status"] for run in history], "gif": True,
         "live_pointer_pixel": [23, 99, 59]}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sessions", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--chrome", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700)
    process = subprocess.Popen([sys.executable, str(ROOT / "dashboard.py"), "--sessions", str(args.sessions),
                                "--history", str(args.output / "history")], stdout=subprocess.PIPE, text=True)
    try:
        url = process.stdout.readline().strip()
        if not url.startswith("http://127.0.0.1:"):
            raise RuntimeError("The local dashboard failed to start.")
        with sync_playwright() as protocol:
            browser = protocol.chromium.launch(executable_path=str(args.chrome), headless=True)
            page = browser.new_page(viewport={"width": 1380, "height": 1080})
            exercise(page, url, args.output)
            browser.close()
        print("The browser exercised two hosted sessions, workflow and failure history, a GIF, and coordinated inputs.")
    finally:
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()
