"""Bounded file exchange through an explicitly enabled runner-private directory."""

import base64
import binascii
from contextlib import contextmanager
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
        self.identity = self.directory.stat()

    @contextmanager
    def directory_handle(self):
        location = self.directory.lstat()
        if not stat.S_ISDIR(location.st_mode) or not os.path.samestat(self.identity, location):
            raise CommandError("unsafe_directory", "The session exchange directory changed.", 409)
        if os.open not in os.supports_dir_fd:
            yield None
            return
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if not os.path.samestat(self.identity, os.fstat(fd)):
                raise CommandError("unsafe_directory", "The session exchange directory changed.", 409)
            yield fd
        finally:
            os.close(fd)

    def file_info(self, name, fd):
        if fd is not None:
            return os.stat(name, dir_fd=fd, follow_symlinks=False)
        return (self.directory / name).lstat()

    def file_open(self, name, flags, fd):
        if fd is not None:
            return os.open(name, flags, 0o600, dir_fd=fd)
        return os.open(self.directory / name, flags, 0o600)

    def file_names(self, fd):
        return os.listdir(fd if fd is not None else self.directory)

    def execute(self, command, params):
        with self.directory_handle() as fd:
            return self.exchange(command, params, fd)

    def exchange(self, command, params, fd):
        if command == "files.list":
            entries = []
            for name in self.file_names(fd):
                try:
                    info = self.file_info(name, fd)
                except FileNotFoundError:
                    continue
                if is_regular(info):
                    entries.append({"name": name, "size": info.st_size})
                if len(entries) >= MAX_FILES:
                    break
            return {"directory": str(self.directory), "entries": sorted(entries, key=lambda item: item["name"])}
        name = params["name"]
        if name.endswith((".", " ")) or name.partition(".")[0].upper() in {
            "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10)),
        }:
            raise CommandError("invalid_filename", "Choose a portable plain filename.")
        if command == "files.stage":
            return self.stage(name, params["base64"], fd)
        return self.read(name, fd)

    def stage(self, name, encoded, fd):
        if len(self.file_names(fd)) >= MAX_FILES:
            raise CommandError("exchange_full", "The session file count has reached its limit.", 413)
        try:
            data = base64.b64decode(encoded, validate=True)
        except binascii.Error:
            raise CommandError("invalid_arguments", "Provide standard base64 file contents.") from None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            handle = self.file_open(name, flags, fd)
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
        except FileExistsError:
            raise CommandError("file_exists", "The filename already exists in this session.", 409) from None
        return {"name": name, "path": str(self.directory / name), "size": len(data)}

    def read(self, name, fd):
        try:
            before = self.file_info(name, fd)
            if not is_regular(before):
                raise CommandError("unsafe_file", "Only regular files in the exchange directory are readable.", 422)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            handle = self.file_open(name, flags, fd)
            with os.fdopen(handle, "rb") as stream:
                current = os.fstat(stream.fileno())
                if not is_regular(current) or not os.path.samestat(before, current):
                    raise CommandError("unsafe_file", "The file changed before it could be opened.", 409)
                data = stream.read(MAX_FILE + 1)
        except FileNotFoundError:
            raise CommandError("file_not_found", "The exchange file does not exist.", 404) from None
        if len(data) > MAX_FILE:
            raise CommandError("file_too_large", "The file exceeds the exchange download limit.", 413)
        return {"name": name, "size": len(data), "base64": base64.b64encode(data).decode("ascii")}
