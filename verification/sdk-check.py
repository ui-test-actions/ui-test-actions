"""Exercise the official MCP client, Python SDK, and cross-device assertions."""

import argparse
import asyncio
from base64 import b64decode
from io import BytesIO
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ui_sdk import SessionGroup


def measure(frame):
    image = Image.open(BytesIO(frame)).convert("RGB")
    delta = ImageChops.difference(image, Image.new("RGB", image.size, (25, 43, 66)))
    lights = [channel.point(lambda value: 255 if value == 0 else 0) for channel in delta.split()]
    bounds = ImageChops.multiply(ImageChops.multiply(*lights[:2]), lights[2]).getbbox()
    if not bounds or bounds[2] - bounds[0] != 560:
        raise RuntimeError("The blue fixture viewport did not match the workflow")
    left, top, right, _ = bounds
    return {"click": {"x": (left + right) // 2, "y": top + 188},
            "pixel": {"x": left + 12, "y": top + 7, "rgb": [23, 99, 59]},
            "crop": bounds}


async def scenario(config, output):
    output.mkdir(mode=0o700)
    group = SessionGroup.open(config)
    devices = group.sessions()
    if sorted(item["target"] for item in devices if item["available"]) != ["linux", "windows"]:
        raise RuntimeError("Expected Linux and Windows live sessions")
    windows = group.device("windows").screenshot()
    (output / "windows-before.png").write_bytes(windows)
    (output / "windows-target.json").write_text(json.dumps(measure(windows)))
    server = StdioServerParameters(command=sys.executable,
        args=[str(ROOT / "mcp_server.py"), "--sessions", str(config), "--output-root", str(output)],
        env={"PYTHONPATH": os.environ.get("PYTHONPATH", "")})
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as client:
            initialize = await client.initialize()
            tools = {tool.name for tool in (await client.list_tools()).tools}

            async def call(name, arguments):
                result = await client.call_tool(name, arguments)
                if result.isError:
                    raise RuntimeError(f"MCP tool {name} reported {result.structuredContent}")
                return result

            picture = await call("ui_screenshot", {"device": "linux"})
            before = b64decode(picture.content[0].data, validate=True)
            geometry = measure(before)
            (output / "linux-before.png").write_bytes(before)
            live = (await call("ui_capabilities", {"device": "linux"})).structuredContent
            if live["api_version"] != 2 or "pointer.click" not in live["commands"]:
                raise RuntimeError("The Linux fixture does not expose the expected live capabilities")
            invalid = await client.call_tool("ui_action", {"device": "linux", "command": "no.such.operation"})
            if not invalid.isError or invalid.structuredContent["http_status"] != 404:
                raise RuntimeError("Unknown action did not return a structured HTTP 404")
            workflow = {"version": 1, "target": "linux", "steps": [{
                "action": {"command": "pointer.click", "params": geometry["click"]},
                "expect": {"pixel": geometry["pixel"]},
            }]}
            result = await call("ui_workflow", {"device": "linux", "workflow": workflow})
            assertion = (await call("ui_assert", {"device": "linux", "expect": {"pixel": geometry["pixel"]}})).structuredContent
            if not assertion["satisfied"]:
                raise RuntimeError("The separate visible condition did not pass")
            frame = await call("ui_screenshot", {"device": "linux"})
            (output / "linux-after.png").write_bytes(b64decode(frame.content[0].data, validate=True))

            text = "مرحبًا ١٢٣ — SDK 🌍"
            for name in ("linux", "windows"):
                await call("ui_action", {"device": name, "command": "clipboard.set", "params": {"text": text}})
            staged = {"version": 1, "inputs": ["expected"], "stages": [{
                "name": "Verify the two actual clipboards agree",
                "devices": {name: {"capture": {f"{name}_clipboard": {"kind": "clipboard_text"}}}
                            for name in ("linux", "windows")},
                "equal": [["linux_clipboard", "expected"], ["windows_clipboard", "expected"]],
            }]}
            coordination = await call("ui_coordinate", {"scenario": staged, "inputs": {"expected": text}})
            report = {"protocol": initialize.protocolVersion, "tools": sorted(tools), "devices": devices,
                      "linux_workflow": result.structuredContent["report"],
                      "cross_device": coordination.structuredContent["report"],
                      "unknown_action": invalid.structuredContent}
            (output / "mcp.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sessions", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    asyncio.run(scenario(args.sessions, args.output))
