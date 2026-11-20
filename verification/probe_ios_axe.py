"""Verify Swift/UIKit semantics and native Unicode paste through the iOS AXe session."""

import argparse
import json
from pathlib import Path

from probe_fixture import Client, screenshot


TEXT = "مرحبًا ١٢٣ — English 🌍"


def choose(client, selector):
    observed = client.command("element.find", {"selector": selector})["result"]
    if observed["matched"] != 1:
        raise AssertionError(f"The expected iOS control was not unique: {selector}")
    return {"id": observed["nodes"][0]["id"], "snapshot_id": observed["snapshot_id"]}


def run(client, evidence):
    session = client.identify()
    capabilities = json.loads(client.fetch("/v2/capabilities"))
    editor = {"role": "AXTextField", "properties": {"editable": True}, "visible": True}
    apply = {"role": "AXButton", "name": "Apply change", "visible": True, "enabled": True}
    screenshot(client).save(evidence / "before.png")
    client.command("element.click", choose(client, editor))
    client.command("text.insert", {"text": TEXT, "replace": True})
    paste = client.command("element.wait", {
        "selector": editor | {"text": TEXT}, "state": "present", "timeout_ms": 9000,
    })["result"]
    client.command("element.click", choose(client, apply))
    updated = client.command("element.wait", {
        "selector": {"name": "AFTER · " + TEXT, "visible": True}, "state": "present", "timeout_ms": 9000,
    })["result"]
    screenshot(client).save(evidence / "after.png")
    result = {
        "target": session["target"], "screen": capabilities["screen"], "unicode_exact": paste["satisfied"],
        "expected_label": "AFTER · " + TEXT, "label_observed": updated["satisfied"],
    }
    (evidence / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    client = Client(json.loads(args.connection.read_text(encoding="utf-8")), args.token_file)
    print(json.dumps(run(client, args.evidence), ensure_ascii=False))
