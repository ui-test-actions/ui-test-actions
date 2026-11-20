"""Capture both authenticated mobile sessions for a P2pKit LAN experiment."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent import Client


def observe(target, artifact, token, output):
    config = json.loads(artifact.read_text(encoding="utf-8"))
    client = Client(config, token)
    description = client.identify()
    if description["target"] != target:
        raise ValueError(f"The {target} connection points to another target")
    image = client.fetch("/v1/screenshot")
    if not image.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"The {target} screenshot was not PNG")
    (output / f"{target}.png").write_bytes(image)
    result = client.command("tree.snapshot", {})
    if not result["ok"]:
        raise RuntimeError(f"The {target} accessibility observation failed")
    fields = ("name", "text", "role", "resource_id", "visible", "enabled", "bounds")
    observation = {
        "target": target, "seconds_remaining": description["seconds_remaining"],
        "nodes": [{field: node[field] for field in fields if field in node} for node in result["result"]["nodes"]],
    }
    (output / f"{target}.json").write_text(json.dumps(observation, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for target in ("android", "ios"):
        parser.add_argument(f"--{target}-connection", required=True, type=Path)
        parser.add_argument(f"--{target}-token", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        android = pool.submit(observe, "android", args.android_connection, args.android_token, args.output)
        ios = pool.submit(observe, "ios", args.ios_connection, args.ios_token, args.output)
        android.result()
        ios.result()


if __name__ == "__main__":
    main()
