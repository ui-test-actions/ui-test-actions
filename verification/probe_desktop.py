"""External proof of the desktop session contract against the hosted fixture."""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Client, ClientError


def expect_error(client, name, args, status):
    try:
        client.command(name, args)
    except ClientError as error:
        if str(error).startswith(f"HTTP {status} "):
            return str(error)
        raise
    raise RuntimeError(f"{name} unexpectedly succeeded")


def exercise(client, target, entry, apply, evidence):
    same = client.identify()["id"]
    results = {"session_id": same, "target": target}
    utf8 = "مرحبًا بالعالم، ١٢٣؟\nMixed English and العربية 🌍"
    client.command("clipboard.set", {"text": utf8})
    assert client.command("clipboard.get", {})["result"]["text"] == utf8
    results["clipboard_unicode_exact"] = True
    filename = "verification-" + uuid4().hex[:8] + ".txt"
    payload = base64.b64encode(utf8.encode()).decode("ascii")
    file = client.command("files.stage", {"name": filename, "base64": payload})["result"]
    assert client.command("files.read", {"name": filename})["result"]["base64"] == payload
    assert any(item["name"] == filename for item in client.command("files.list", {})["result"]["entries"])
    results["exchange_bytes_exact"] = file["size"]
    results["duplicate_file"] = expect_error(client, "files.stage", {"name": filename, "base64": payload}, 409)
    results["path_traversal"] = expect_error(client, "files.read", {"name": "../private"}, 400)

    baseline = client.command("visual.sample", {"region": {"x": 70, "y": 100, "width": 540, "height": 300}})
    client.command("recording.start", {"duration_seconds": 6})
    time.sleep(.7)
    steps = [
        {"command": "pointer.move", "params": {"x": entry[0], "y": entry[1], "duration_ms": 160}},
        {"command": "pointer.click", "params": {"x": entry[0], "y": entry[1]}},
        {"command": "text.insert", "params": {"text": "v2 verification", "replace": True}},
        {"command": "pointer.click", "params": {"x": apply[0], "y": apply[1]}},
    ]
    request_id = "fixture-" + uuid4().hex
    original = client.batch(steps, request_id)
    assert original["completed"] == len(steps) and original == client.batch(steps, request_id)
    results["batch_steps_and_replay"] = original["completed"]
    time.sleep(1)
    results["visual"] = client.command("visual.wait", {
        "baseline": baseline["result"]["baseline"], "threshold": 2, "timeout_ms": 5000,
    })["result"]
    results["recording"] = client.command("recording.stop", {})["result"]
    capture = client.fetch("/v2/recording")
    assert capture.startswith(b"GIF8")
    (evidence / "recording.gif").write_bytes(capture)
    (evidence / "after.png").write_bytes(client.fetch("/v1/screenshot"))
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=6) as pool:
        observations = list(pool.map(lambda _: client.identify()["id"], range(24)))
    assert all(item == same for item in observations)
    results["parallel_read_requests"] = {"count": len(observations), "elapsed_seconds": round(time.monotonic() - started, 3)}
    (evidence / "matrix.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--entry", type=int, nargs=2, required=True)
    parser.add_argument("--apply", type=int, nargs=2, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    connection = json.loads(args.connection.read_text(encoding="utf-8"))
    args.evidence.mkdir(parents=True, exist_ok=True)
    exercise(Client(connection, args.token_file), connection["target"], args.entry, args.apply, args.evidence)
