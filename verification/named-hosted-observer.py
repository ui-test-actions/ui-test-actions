"""Observe a separate host job using a bearer and Access credentials held by Actions."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Client, ClientError
from verification.transports.check import observe, remote_controls


def probe(client):
    started = time.monotonic()
    stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    try:
        state = client.identify()
        return {"at": stamp, "http": 200, "remaining": state["seconds_remaining"],
                "latency_ms": round((time.monotonic() - started) * 1000)}
    except ClientError as error:
        return {"at": stamp, "http": error.status, "latency_ms": round((time.monotonic() - started) * 1000)}


def status_once(client):
    try:
        client.fetch("/v1/session", retries=0)
    except ClientError as error:
        return error.status
    return 200


def main():
    run = os.environ["HOST_RUN"]
    mode = os.environ["MODE"]
    if not re.fullmatch(r"[0-9]+", run) or mode not in {"expiry", "cancellation"}:
        raise ValueError("Invalid observer inputs")
    raw = os.environ.pop("OBSERVER_BEARER")
    access = {"client_id": os.environ.pop("ACCESS_ID"), "client_secret": os.environ.pop("ACCESS_SECRET")}
    if not re.fullmatch(r"[0-9a-f]{64}", raw) or not all(access.values()):
        raise RuntimeError("Configure the observer's test bearer and Access credentials.")
    output = Path(os.environ["RUNNER_TEMP"]) / "named-public"
    output.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        bearer, access_file = work / "bearer", work / "access.json"
        bearer.write_text(raw, encoding="ascii")
        access_file.write_text(json.dumps(access), encoding="utf-8")
        bearer.chmod(0o600)
        access_file.chmod(0o600)
        end = time.monotonic() + 480
        while time.monotonic() < end:
            subprocess.run(["gh", "run", "download", run, "--pattern", "ui-session-*", "-D", directory],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25)
            artifacts = list(work.glob("ui-session-*/connection.json"))
            if len(artifacts) == 1:
                break
            time.sleep(4)
        else:
            raise RuntimeError("No unique connection artifact from host workflow.")
        cfg = json.loads(artifacts[0].read_text())
        if cfg.get("url") != "https://uitest.abdelrahmanfahmy.dev" or cfg.get("transport") != "cloudflare-named":
            raise RuntimeError("Unexpected origin in connection artifact.")
        client = Client(cfg, bearer, access_file)
        initial = client.identify()
        expected_denials = {302, 303, 307, 308, 401, 403}
        anonymous = Client(cfg, bearer, access_file)
        for name in ("CF-Access-Client-Id", "CF-Access-Client-Secret"):
            anonymous.headers.pop(name)
        wrong = Client(cfg, bearer, access_file)
        wrong.headers["CF-Access-Client-Secret"] = "invalid-acceptance-credential"
        missing_edge, invalid_edge = status_once(anonymous), status_once(wrong)
        if missing_edge not in expected_denials or invalid_edge not in expected_denials:
            raise RuntimeError(f"Access did not deny one of the requests ({missing_edge}, {invalid_edge}).")
        stale = Client(cfg, bearer, access_file)
        stale.headers["X-UI-Session-ID"] = "0" * 24
        if status_once(stale) != 409:
            raise RuntimeError("A mismatched session identity was accepted.")
        report = {
            "host_run": int(run), "mode": mode, "opening": initial["seconds_remaining"],
            "missing_access_http": missing_edge, "invalid_access_http": invalid_edge, "wrong_session_http": 409,
            "journey": observe(cfg, bearer, remote_controls(client), output, access_file),
        }
        if mode == "expiry":
            report["samples"] = samples = []
            deadline = time.monotonic() + initial["seconds_remaining"] + 45
            while time.monotonic() < deadline:
                samples.append(probe(client))
                if len(samples) >= 2 and all(item["http"] in (410, 502, 503, 530) for item in samples[-2:]):
                    break
                time.sleep(1.5 if samples[-1].get("remaining", 0) < 15 else 6)
            live = [item for item in samples if item["http"] == 200]
            passed = (len(live) >= 3 and live[-1]["remaining"] <= 15
                      and all(item["http"] == 200 for item in samples[:-2])
                      and all(item["http"] in (410, 502, 503, 530) for item in samples[-2:]))
        else:
            print("External observation complete. Ready for cancellation.", flush=True)
            report["samples"] = samples = []
            deadline = time.monotonic() + min(130, initial["seconds_remaining"] - 35)
            while time.monotonic() < deadline:
                samples.append(probe(client))
                if len(samples) >= 2 and all(item["http"] in (410, 502, 503, 530) for item in samples[-2:]):
                    break
                time.sleep(2)
            live = [item for item in samples if item["http"] == 200]
            passed = (bool(live) and live[-1]["remaining"] > 30
                      and all(item["http"] in (410, 502, 503, 530) for item in samples[-2:]))
        report["passed"] = passed
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if not passed:
            raise RuntimeError("The external endpoint did not show a stable live session and terminal closure.")


if __name__ == "__main__":
    main()
