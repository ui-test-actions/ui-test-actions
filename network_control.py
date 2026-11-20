"""Connect the UI protocol to a workflow-owned isolated link controller."""

import json
from pathlib import Path
import os
import socket
import stat

from contract import CommandError, NETWORK_PROFILE, validate


NETWORK_COMMANDS = ("network.profile.get", "network.profile.set", "network.profile.reset")
MAX_MESSAGE = 2048


class NetworkControl:
    def __init__(self, path: Path, runner_temp: Path):
        path = path.absolute()
        parent = path.parent.resolve(strict=True)
        directory = parent.stat()
        if (not hasattr(socket, "AF_UNIX") or parent == runner_temp.resolve() or
                not parent.is_relative_to(runner_temp.resolve()) or
                not hasattr(os, "getuid") or directory.st_uid != os.getuid() or directory.st_mode & 0o077):
            raise ValueError("Configure a private control directory owned by the runner user inside RUNNER_TEMP.")
        self.path = parent / path.name

    def execute(self, name, params):
        if name not in NETWORK_COMMANDS:
            raise ValueError("Unknown isolated network command.")
        try:
            endpoint = self.path.lstat()
            if not stat.S_ISSOCK(endpoint.st_mode) or endpoint.st_uid != os.getuid() or endpoint.st_mode & 0o077:
                raise OSError("The link controller socket is not private.")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(2)
                connection.connect(os.fspath(self.path))
                connection.sendall(json.dumps({"command": name, "params": params}).encode() + b"\n")
                with connection.makefile("rb") as stream:
                    line = stream.readline(MAX_MESSAGE + 1)
            if len(line) > MAX_MESSAGE or not line.endswith(b"\n"):
                raise ValueError("Invalid link controller reply.")
            reply = json.loads(line)
            required = {"profile", "generation", "remaining_ms"}
            if not isinstance(reply, dict) or not required <= reply.keys() or reply.keys() - required - {"controller_epoch_ms"}:
                raise ValueError("Invalid link controller reply.")
            validate(reply["profile"], NETWORK_PROFILE, "profile")
            for field in reply.keys() - {"profile"}:
                if type(reply[field]) is not int or reply[field] < 0:
                    raise ValueError("Invalid link controller reply.")
            return reply
        except (OSError, TypeError, ValueError) as error:
            raise CommandError("network_unavailable", "The isolated link controller did not confirm the command.", 502) from error
