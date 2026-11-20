"""Workflow-allowlisted desktop processes, owned by the live session."""

import json
from pathlib import Path
import re
import shutil
import subprocess

from contract import CommandError


class DesktopApps:
    def __init__(self, driver, configuration):
        self.driver = driver
        self.apps = {}
        self.running = {}
        definitions = json.loads(configuration)
        if not isinstance(definitions, dict) or len(definitions) > 16:
            raise ValueError("desktop-apps must be an object with at most 16 application definitions.")
        for identifier, spec in definitions.items():
            if (not re.fullmatch(r"[a-zA-Z0-9_.-]{1,255}", identifier)
                    or not isinstance(spec, dict) or set(spec) - {"argv", "cwd"}):
                raise ValueError("Each desktop application needs an ID and an argv array.")
            argv = spec.get("argv")
            if (not isinstance(argv, list) or not 1 <= len(argv) <= 64
                    or any(not isinstance(item, str) or "\x00" in item for item in argv)
                    or not argv[0]):
                raise ValueError("Each desktop application needs a valid argv array.")
            binary = shutil.which(argv[0])
            if not binary:
                raise ValueError("A configured desktop application executable is unavailable.")
            cwd = Path(spec.get("cwd", Path.cwd())).resolve()
            if not cwd.is_dir():
                raise ValueError("A configured desktop application working directory is unavailable.")
            self.apps[identifier] = ([binary, *argv[1:]], cwd)

    def capabilities(self):
        commands = set(self.driver.capabilities())
        if self.apps:
            commands.update(("app.status", "app.launch", "app.close", "app.restart"))
        return commands

    def execute(self, command, params):
        if not command.startswith("app."):
            return self.driver.execute(command, params)
        identifier = params["id"]
        if identifier not in self.apps:
            raise CommandError("unapproved_app", "This desktop application is outside the workflow allowlist.", 403)
        current = self.running.get(identifier)
        if command in ("app.close", "app.restart"):
            self.terminate(current)
        if command == "app.restart" or command == "app.launch" and (not current or current.poll() is not None):
            argv, cwd = self.apps[identifier]
            current = subprocess.Popen(
                argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.running[identifier] = current
        status = current.poll() if current is not None else None
        return {"id": identifier, "running": current is not None and status is None, "exit_code": status}

    @staticmethod
    def terminate(process):
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def close(self):
        for process in self.running.values():
            self.terminate(process)
