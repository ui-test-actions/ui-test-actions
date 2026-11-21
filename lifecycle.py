"""Publish the connection file, then hold the GitHub job open for the UI server."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from lease import HoldLease


def show_log(directory):
    log = directory / "session.log"
    if log.exists():
        print(log.read_text(encoding="utf-8", errors="replace"), end="", flush=True)


def start():
    signal.signal(signal.SIGTERM, interrupt)
    work = Path(tempfile.mkdtemp(prefix="ui-session-", dir=os.environ["RUNNER_TEMP"]))
    if os.name == "nt":
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        options = {"start_new_session": True}
    with (work / "session.log").open("wb") as log:
        server = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("session.py")), str(work)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **options,
        )
    connection = work / "connection.json"
    try:
        deadline = time.monotonic() + int(os.environ["UI_TEST_STARTUP_TIMEOUT"]) + 600
        while not connection.exists():
            if server.poll() is not None:
                show_log(work)
                raise RuntimeError(f"UI server exited with status {server.returncode}")
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out waiting for the UI session to start")
            time.sleep(0.25)
        show_log(work)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"file={connection.as_posix()}\n")
            session_id = json.loads(connection.read_text(encoding="utf-8"))["session_id"]
            output.write(f"session-id={session_id}\n")
    except BaseException:
        (work / "stop").touch()
        raise


def interrupt(*_args):
    raise KeyboardInterrupt


def hold():
    signal.signal(signal.SIGTERM, interrupt)
    work = Path(os.environ["UI_TEST_CONNECTION_FILE"]).parent
    if os.environ["UI_TEST_PUBLISH_OUTCOME"] != "success":
        (work / "stop").touch()
        raise RuntimeError("Connection file upload failed")
    try:
        outcome = work / "outcome"
        heartbeat = work / HoldLease.heartbeat
        renew = 0
        deadline = time.monotonic() + int(os.environ["UI_TEST_DURATION"]) * 60 + 45
        while not outcome.exists():
            now = time.monotonic()
            if now >= deadline:
                raise RuntimeError("UI server did not report completion")
            if now >= renew:
                heartbeat.touch()
                renew = now + 2
            time.sleep(0.5)
        if outcome.read_text(encoding="utf-8") != "success":
            show_log(work)
            raise RuntimeError("Live UI session failed")
        print("UI session closed")
    finally:
        (work / "stop").touch()


if __name__ == "__main__":
    try:
        {"start": start, "hold": hold}[sys.argv[1]]()
    except KeyboardInterrupt:
        sys.exit(130)
