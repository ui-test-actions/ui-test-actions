"""Bounded file exchange through an explicitly enabled runner-private directory."""

import base64
import binascii
import os
from pathlib import Path
import stat

from contract import CommandError


MAX_FILE = 128 * 1024
MAX_FILES = 24


def is_regular(info):
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


class Exchange:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700)

    def execute(self, command, params):
        if command == "files.list":
            entries = []
            for path in self.directory.iterdir():
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                if is_regular(info):
                    entries.append({"name": path.name, "size": info.st_size})
                if len(entries) >= MAX_FILES:
                    break
            return {"directory": str(self.directory), "entries": sorted(entries, key=lambda item: item["name"])}
        name = params["name"]
        if name.endswith((".", " ")) or name.partition(".")[0].upper() in {
            "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10)),
        }:
            raise CommandError("invalid_filename", "Choose a portable plain filename.")
        path = self.directory / name
        if command == "files.stage":
            return self.stage(path, params["base64"])
        return self.read(path)

    def stage(self, path, encoded):
        if sum(1 for _ in self.directory.iterdir()) >= MAX_FILES:
            raise CommandError("exchange_full", "The session file count has reached its limit.", 413)
        try:
            data = base64.b64decode(encoded, validate=True)
        except binascii.Error:
            raise CommandError("invalid_arguments", "Provide standard base64 file contents.") from None
        try:
            with path.open("xb") as stream:
                stream.write(data)
        except FileExistsError:
            raise CommandError("file_exists", "The filename already exists in this session.", 409) from None
        return {"name": path.name, "path": str(path), "size": len(data)}

    def read(self, path):
        try:
            before = path.lstat()
            if not is_regular(before):
                raise CommandError("unsafe_file", "Only regular files in the exchange directory are readable.", 422)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as stream:
                current = os.fstat(stream.fileno())
                if not is_regular(current) or not os.path.samestat(before, current):
                    raise CommandError("unsafe_file", "The file changed before it could be opened.", 409)
                data = stream.read(MAX_FILE + 1)
        except FileNotFoundError:
            raise CommandError("file_not_found", "The exchange file does not exist.", 404) from None
        if len(data) > MAX_FILE:
            raise CommandError("file_too_large", "The file exceeds the exchange download limit.", 413)
        return {"name": path.name, "size": len(data), "base64": base64.b64encode(data).decode("ascii")}
