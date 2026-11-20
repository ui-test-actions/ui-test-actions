"""Extract test labels and their screen coordinates from a visible Simulator capture."""

import csv
from io import BytesIO, StringIO
import subprocess

from PIL import Image


def read(png, binary, crop):
    left, top, right, bottom = crop
    with Image.open(BytesIO(png)) as image:
        if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
            raise ValueError("iOS crop is outside the runner screenshot")
        region = image.crop(crop).resize(((right - left) * 3, (bottom - top) * 3), Image.Resampling.LANCZOS)
        data = BytesIO()
        region.save(data, "PNG")
    process = subprocess.run([str(binary), "stdin", "stdout", "--psm", "11", "tsv"],
                             input=data.getvalue(), capture_output=True, check=True, timeout=8)
    lines = {}
    for row in csv.DictReader(StringIO(process.stdout.decode("utf-8")), delimiter="\t"):
        if row["level"] == "5" and row["text"].strip() and float(row["conf"]) >= 25:
            key = tuple(row[field] for field in ("block_num", "par_num", "line_num"))
            lines.setdefault(key, []).append(row)
    for words in lines.values():
        x, y = min(int(word["left"]) for word in words), min(int(word["top"]) for word in words)
        xx = max(int(word["left"]) + int(word["width"]) for word in words)
        yy = max(int(word["top"]) + int(word["height"]) for word in words)
        yield {"label": " ".join(word["text"] for word in words),
               "center": (left + (x + xx) // 6, top + (y + yy) // 6)}
        if len(words) > 1:
            for word in words:
                yield {"label": word["text"],
                       "center": (left + (2 * int(word["left"]) + int(word["width"])) // 6,
                                  top + (2 * int(word["top"]) + int(word["height"])) // 6)}
