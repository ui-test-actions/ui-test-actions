"""Short, bounded visual recordings that remain private to the session."""

import io
import subprocess
import threading
import time

from contract import CommandError


class Recording:
    def __init__(self, session):
        self.session = session
        self.frames = []
        self.latest = b""
        self.result = None
        self.stop = threading.Event()
        self.thread = None
        self.failed = False

    def start(self, duration):
        if self.thread and self.thread.is_alive():
            raise CommandError("recording_active", "A recording is already running.", 409)
        self.frames.clear()
        self.latest = b""
        self.result = None
        self.failed = False
        self.stop.clear()
        deadline = min(time.monotonic() + duration, self.session.deadline)
        self.thread = threading.Thread(target=self.capture, args=(deadline,), daemon=True)
        self.thread.start()
        return {"duration_seconds": duration, "frames_per_second": 2, "format": "gif"}

    def capture(self, deadline):
        from PIL import Image
        while not self.stop.is_set() and time.monotonic() < deadline:
            if self.session.lock.acquire(blocking=False):
                try:
                    if time.monotonic() >= self.session.deadline:
                        return
                    with Image.open(io.BytesIO(self.session.capture())) as png:
                        image = png.convert("RGB")
                    image.thumbnail((512, 512))
                    self.frames.append(image.quantize(colors=128))
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                    self.failed = True
                    return
                finally:
                    self.session.lock.release()
            self.stop.wait(0.5)

    def finish(self):
        if self.thread is None:
            raise CommandError("recording_missing", "Start a recording first.", 404)
        self.stop.set()
        if self.result is not None:
            return self.result
        if not self.frames:
            raise CommandError("recording_empty", "No frames were captured. Start a new recording.", 422)
        first, *frames = self.frames
        output = io.BytesIO()
        first.save(output, format="GIF", save_all=True, append_images=frames, duration=500, loop=0, optimize=False)
        self.latest = output.getvalue()
        self.result = {"frames": len(self.frames), "bytes": len(self.latest),
                       "partial": self.failed, "download": "/v2/recording"}
        self.frames.clear()
        return self.result
