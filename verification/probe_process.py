"""Drive an allowlisted fixture through a real exit and relaunch."""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Client, ClientError


def probe(client, evidence):
    session = client.identify()
    capabilities = json.loads(client.fetch("/v2/capabilities"))
    assert session["target"] == capabilities["target"]
    if session["target"] == "linux":
        assert capabilities["screen"] == {"width": 1024, "height": 768}

    def sample():
        return client.command("visual.sample", {
            "region": {"x": 75, "y": 100, "width": 530, "height": 300},
        })["result"]["baseline"]

    def changed(baseline):
        return client.command("visual.wait", {
            "baseline": baseline, "threshold": 2, "timeout_ms": 6000,
        })["result"]["difference"]

    def image(name):
        (evidence / f"{name}.png").write_bytes(client.fetch("/v1/screenshot"))

    try:
        client.command("app.launch", {"id": "outside-scope"})
    except ClientError as error:
        assert str(error).startswith("HTTP 403 ")
    else:
        raise RuntimeError("Non-allowlisted app launch succeeded")
    app = {"id": "fixture"}
    baseline = sample()
    assert client.command("app.launch", app)["result"]["running"]
    diff_launch = changed(baseline)
    image("launched")
    before_crash = sample()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status = client.command("app.status", app)["result"]
        if not status["running"]:
            break
        time.sleep(.5)
    assert status["exit_code"] == 17, status
    diff_crash = changed(before_crash)
    image("crashed")
    before_restart = sample()
    assert client.command("app.restart", app)["result"]["running"]
    diff_restart = changed(before_restart)
    image("restarted")
    assert not client.command("app.close", app)["result"]["running"]
    result = {"target": session["target"], "screen": capabilities["screen"],
              "observed_exit": status["exit_code"], "unapproved_id_rejected": True,
              "visual_differences": {"launch": diff_launch, "crash": diff_crash, "restart": diff_restart}}
    (evidence / "recovery.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    probe(Client(json.loads(args.connection.read_text()), args.token_file), args.evidence)
