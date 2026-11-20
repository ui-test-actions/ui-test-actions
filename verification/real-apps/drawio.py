"""Seed and independently verify a saved diagram from the browser journey."""

import argparse
import base64
import hashlib
from html import unescape
import json
from pathlib import Path
import re
from urllib.parse import quote, unquote
from urllib.request import urlopen
import xml.etree.ElementTree as ET
from zipfile import ZipFile
import zlib


SEED = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="probe" value="Original label" vertex="1" parent="1" style="rounded=0;whiteSpace=wrap;html=1;">'
        '<mxGeometry x="120" y="120" width="160" height="80" as="geometry"/>'
        '</mxCell></root></mxGraphModel>')
EXPECTED = "مسار الاختبار ١٢٣ — Web UI 🌍"


def prepare(directory, evidence):
    pin = json.loads(Path(__file__).with_name("apps.json").read_text(encoding="utf-8"))["linux-web"]
    url = f'https://github.com/{pin["repository"]}/releases/download/{pin["ref"]}/{pin["asset"]}'
    directory.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    archive = directory / "draw.war"
    with urlopen(url, timeout=30) as response, archive.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != pin["sha256"]:
            raise ValueError("The draw.io release checksum did not match.")
    with ZipFile(archive) as release:
        release.extractall(directory / "web")
    compress = zlib.compressobj(wbits=-15)
    encoded = base64.b64encode(compress.compress(quote(SEED, safe="").encode()) + compress.flush()).decode()
    (directory / "url").write_text("http://127.0.0.1:8765/index.html?offline=1&pwa=0#R" + encoded)
    profile = directory / "chrome" / "Default"
    profile.mkdir(parents=True)
    (profile / "Preferences").write_text(json.dumps({
        "download": {"default_directory": str(evidence.resolve()), "prompt_for_download": False},
    }))


def diagrams(path):
    root = ET.parse(path).getroot()
    if root.tag == "mxGraphModel":
        yield root
    for page in root.findall("diagram"):
        model = page.find("mxGraphModel")
        if model is not None:
            yield model
        elif page.text:
            data = zlib.decompress(base64.b64decode(page.text.strip()), -15)
            yield ET.fromstring(unquote(data.decode()))


def verify(evidence):
    for file in sorted(evidence.glob("*.drawio")):
        for graph in diagrams(file):
            shape = graph.find(".//mxCell[@id='probe']")
            if shape is None:
                continue
            displayed = unescape(re.sub(r"<[^>]*>", "", shape.get("value", ""))).strip()
            geometry = shape.find("mxGeometry")
            if displayed != EXPECTED or geometry is None:
                continue
            position = [float(geometry.get(key, "0")) for key in ("x", "y")]
            if position == [120, 120]:
                continue
            result = {"app": "draw.io", "label": displayed, "original_position": [120, 120],
                      "saved_position": position, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
            (evidence / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            return
    raise SystemExit("The browser did not save the expected Unicode label and changed shape position.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    if args.operation == "prepare":
        prepare(args.directory, args.evidence)
    else:
        verify(args.evidence)
