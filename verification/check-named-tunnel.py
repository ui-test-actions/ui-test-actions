"""Check both authorization layers, reconnect, and expiry on a configured Named Tunnel."""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Client, ClientError
from verification.transports.check import observe, remote_controls


def rejected(client, valid_statuses):
    try:
        client.fetch("/v1/session", retries=0)
    except ClientError as error:
        if error.status in valid_statuses:
            return error.status
        raise RuntimeError(f"Unexpected authorization response HTTP {error.status}") from None
    raise RuntimeError("An invalid credential was accepted.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--access-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.connection.read_text(encoding="utf-8"))
    client = Client(config, args.token_file, args.access_file)
    initial = client.identify()
    valid = Client(config, args.token_file, args.access_file)
    assert valid.identify()["id"] == initial["id"]
    origin_auth = Client(config, args.token_file, args.access_file)
    origin_auth.headers.pop("Authorization")
    report = {"target": initial["target"], "opening_countdown": initial["seconds_remaining"],
              "runner_auth_rejection": rejected(origin_auth, {401}), "reconnected": True}
    if args.access_file:
        edge_auth = Client(config, args.token_file, args.access_file)
        edge_auth.headers.pop("CF-Access-Client-Id")
        edge_auth.headers.pop("CF-Access-Client-Secret")
        wrong_edge_auth = Client(config, args.token_file, args.access_file)
        wrong_edge_auth.headers["CF-Access-Client-Secret"] = "invalid-acceptance-credential"
        denials = {302, 303, 307, 308, 401, 403}
        report["edge_access_rejection"] = rejected(edge_auth, denials)
        report["invalid_edge_access_rejection"] = rejected(wrong_edge_auth, denials)
    stale = Client(config, args.token_file, args.access_file)
    if client.session_id:
        stale.headers["X-UI-Session-ID"] = "0" * 24
        report["wrong_session_rejection"] = rejected(stale, {409})
    args.output.mkdir(mode=0o700)
    report["visual_journey"] = observe(config, args.token_file, remote_controls(valid), args.output, args.access_file)
    deadline = time.monotonic() + initial["seconds_remaining"] + 45
    last = initial["seconds_remaining"]
    closed = []
    while time.monotonic() < deadline and len(closed) < 2:
        try:
            response = json.loads(valid.fetch("/v1/session", retries=0))
            if response["id"] != initial["id"]:
                raise RuntimeError("The configured hostname served a different session.")
            last = response["seconds_remaining"]
            closed.clear()
        except ClientError as error:
            if last > 15 or error.status not in {410, 502, 503, 530}:
                raise
            closed.append(error.status)
        time.sleep(min(4, max(1, last - 8)))
    if len(closed) != 2:
        raise RuntimeError("The named connector did not show confirmed terminal access responses.")
    report.update(last_live_seconds_remaining=last, terminal_http=closed)
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
