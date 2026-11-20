"""Start an optional loopback browser inspector for the configured UI sessions."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
from tempfile import mkdtemp
from threading import Lock
from urllib.parse import urlsplit

from agent import ClientError
from contract import OPERATION_REQUEST, choice, obj, string, validate
from ui_sdk import SessionGroup
from workflow import read_mapping


ASSETS = {"/": ("index.html", "text/html; charset=utf-8"), "/dashboard.css": ("dashboard.css", "text/css"),
          "/dashboard.js": ("dashboard.js", "text/javascript")}
MAX_INPUT = 256 * 1024
RUN_REQUEST = obj(("mode", "definition"), mode=choice("workflow", "coordinate"), device=string(64),
                  definition={"type": "object"}, inputs={"type": "object"})
HISTORY_ID = re.compile(r"[a-f0-9]{32}")
ARTIFACTS = {"before.png", "after.png", "failure.png"}


class Dashboard:
    def __init__(self, sessions, history):
        self.sessions = sessions
        self.history = history.resolve()
        self.history.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.token = secrets.token_hex(32)
        self.writer = Lock()
        self.active = None
        self.executor = ThreadPoolExecutor(max_workers=1)

    @staticmethod
    def save(path, value):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def start(self, request):
        validate(request, RUN_REQUEST, "workflow")
        mode = request["mode"]
        if mode == "workflow" and "device" not in request:
            raise ValueError("Select a device for the workflow.")
        device = self.sessions.device(request["device"]) if mode == "workflow" else None
        if not self.writer.acquire(blocking=False):
            return None
        run_id = secrets.token_hex(16)
        folder = self.history / run_id
        summary = {"id": run_id, "mode": mode, "device": request.get("device"), "status": "running",
                   "started_at": datetime.now(UTC).isoformat(timespec="seconds")}
        try:
            folder.mkdir(mode=0o700)
            self.active = run_id
            self.save(folder / "summary.json", summary)
            self.executor.submit(self.run, folder, request, summary.copy(), device)
        except (OSError, RuntimeError):
            self.active = None
            self.writer.release()
            raise
        return summary

    def run(self, folder, request, summary, device):
        try:
            runner = device.run if device else self.sessions.coordinate
            report = runner(request["definition"], folder / "result", inputs=request.get("inputs"))
            summary["status"] = report["status"]
        except (ClientError, ValueError, TypeError, KeyError, OSError, RecursionError):
            summary.update(status="failed", message="The workflow could not run with the supplied definition or session.")
        finally:
            summary["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            try:
                self.save(folder / "summary.json", summary)
            finally:
                self.active = None
                self.writer.release()

    def folder(self, name):
        if not HISTORY_ID.fullmatch(name):
            raise LookupError
        folder = self.history / name
        if not folder.is_dir() or folder.is_symlink():
            raise LookupError
        return folder

    def recent(self):
        folders = (path for path in self.history.iterdir() if HISTORY_ID.fullmatch(path.name)
                   and path.is_dir() and not path.is_symlink())
        recent = sorted(folders, key=lambda path: path.stat().st_mtime_ns, reverse=True)[:30]
        summaries = []
        for path in recent:
            if (summary_path := path / "summary.json").is_file() and not summary_path.is_symlink():
                value = read_mapping(summary_path)
                if value.get("status") == "running" and self.active != value.get("id"):
                    value["status"] = "interrupted"
                summaries.append(value)
        return summaries


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(20)
        super().setup()

    def log_message(self, *_args):
        pass

    def reply(self, status, value, kind="application/json"):
        payload = json.dumps(value, ensure_ascii=False).encode() if kind == "application/json" else value
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' blob:; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def error(self, status, code, message):
        self.reply(status, {"error": {"code": code, "message": message}})

    def route(self, mutate=False):
        state = self.server.dashboard
        host = f"127.0.0.1:{self.server.server_port}"
        origin = self.headers.get("Origin")
        if self.headers.get("Host") != host or (origin and origin != f"http://{host}"):
            return self.error(403, "origin_rejected", "Use the dashboard's exact loopback address.")
        parsed = urlsplit(self.path)
        path = parsed.path
        if parsed.netloc or parsed.query:
            return self.error(400, "invalid_route", "Use a dashboard path without query parameters.")
        if not mutate and path in ASSETS:
            filename, kind = ASSETS[path]
            return self.reply(200, (Path(__file__).with_name("dashboard_assets") / filename).read_bytes(), kind)
        bearer = self.headers.get("Authorization", "")
        if len(bearer) != 71 or not bearer.isascii() or not compare_digest(bearer, "Bearer " + state.token):
            return self.error(401, "unauthorized", "Open the private dashboard link from its local process.")
        if mutate and origin != f"http://{host}":
            return self.error(403, "origin_required", "Send browser mutations from the dashboard origin.")
        segments = path.split("/")[1:]
        try:
            if mutate:
                self.write_api(state, segments)
            else:
                self.read_api(state, segments)
        except ClientError as error:
            data = (error.payload or {}).get("error", {})
            code = data.get("code", "") if isinstance(data, dict) else ""
            if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
                code = "runner_unavailable"
            self.error(error.status or 502, code, "The active runner rejected or could not complete the request.")
        except LookupError:
            self.error(404, "not_found", "This device, report, or dashboard action was unavailable.")
        except (ValueError, TypeError, OSError, RecursionError):
            self.error(400, "invalid_request", "The dashboard could not use the supplied input.")

    def read_api(self, state, segments):
        if segments == ["api", "devices"]:
            return self.reply(200, {"sessions": state.sessions.sessions()})
        if segments == ["api", "history"]:
            return self.reply(200, {"runs": state.recent()})
        if len(segments) >= 3 and segments[:2] == ["api", "history"]:
            folder = state.folder(segments[2])
            if len(segments) == 3:
                summary_path = folder / "summary.json"
                if summary_path.is_symlink():
                    raise LookupError
                summary = read_mapping(summary_path)
                if summary.get("status") == "running" and state.active != summary.get("id"):
                    summary["status"] = "interrupted"
                report = folder / "result" / "report.json"
                present = sorted(name for name in ARTIFACTS if (folder / "result" / name).is_file())
                return self.reply(200, {"summary": summary, "artifacts": present,
                                        "report": read_mapping(report) if report.is_file() and report.resolve().is_relative_to(folder) else None})
            if len(segments) == 4 and segments[3] in ARTIFACTS:
                image = folder / "result" / segments[3]
                if image.is_file() and image.resolve().is_relative_to(folder):
                    return self.reply(200, image.read_bytes(), "image/png")
        if len(segments) == 4 and segments[:2] == ["api", "device"]:
            device = state.sessions.device(segments[2])
            operation = segments[3]
            if operation == "screenshot":
                return self.reply(200, device.screenshot(), "image/png")
            if operation == "recording":
                return self.reply(200, device.recording(), "image/gif")
            if operation == "tree":
                return self.reply(200, device.inspect(350))
            if operation == "capabilities":
                value = device.capabilities()
                value.pop("id", None)
                return self.reply(200, value)
            if operation == "diagnostics":
                provided = device.capabilities()["commands"]
                value = {}
                if "performance.observations" in provided:
                    value["timing"] = device.action("performance.observations")["result"]
                if "diagnostics.sources" in provided:
                    names = device.action("diagnostics.sources")["result"]["sources"]
                    value["events"] = [device.action("diagnostics.events", {"source": name})["result"] for name in names]
                return self.reply(200, value)
        raise LookupError

    def write_api(self, state, segments):
        size = int(self.headers.get("Content-Length", "0"))
        if self.headers.get_content_type() != "application/json" or not 1 <= size <= MAX_INPUT:
            raise ValueError("Invalid request body.")
        body = json.loads(self.rfile.read(size))
        if segments == ["api", "run"]:
            started = state.start(body)
            if started:
                return self.reply(202, started)
        elif len(segments) == 4 and segments[:2] == ["api", "device"] and segments[3] == "action":
            validate(body, OPERATION_REQUEST, "action")
            if state.writer.acquire(blocking=False):
                try:
                    device = state.sessions.device(segments[2])
                    return self.reply(200, device.action(body["command"], body.get("params"), request_id=body.get("request_id")))
                finally:
                    state.writer.release()
        else:
            raise LookupError
        return self.error(409, "dashboard_busy", "Wait for the current dashboard operation to finish.")

    def do_GET(self):
        self.route()

    def do_POST(self):
        self.route(mutate=True)


def create_server(group, history, port=0):
    dashboard = Dashboard(group, history)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.dashboard = dashboard
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", required=True, type=Path)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    with create_server(SessionGroup.open(args.sessions), args.history or Path(mkdtemp(prefix="ui-dashboard-")), args.port) as server:
        print(f"http://127.0.0.1:{server.server_port}/#access={server.dashboard.token}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.dashboard.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
