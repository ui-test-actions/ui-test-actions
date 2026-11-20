"""Python interface to the existing live UI, replay, and device engines."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from agent import Client, ClientError
from coordinate import load_devices, run_scenario
from contract import validate
from explore import ASSERTION, PNG, UI, validate_assertion
from workflow import read_mapping, replay


class LiveUI:
    def __init__(self, client):
        self.client = client

    @classmethod
    def open(cls, connection: Path, token_file: Path, access_file: Path | None = None):
        return cls(Client(read_mapping(connection), token_file, access_file))

    def identify(self):
        return self.client.identify()

    def capabilities(self):
        self.identify()
        return json.loads(self.client.fetch("/v2/capabilities"))

    def screenshot(self):
        self.identify()
        image = self.client.fetch("/v1/screenshot")
        if not image.startswith(PNG) or len(image) > 24 * 1024 * 1024:
            raise ClientError("The session returned an invalid PNG.")
        return image

    def recording(self):
        self.identify()
        image = self.client.fetch("/v2/recording")
        if not image.startswith(b"GIF8") or len(image) > 24 * 1024 * 1024:
            raise ClientError("The session returned an invalid GIF.")
        return image

    def action(self, command, params=None, *, request_id=None):
        self.identify()
        return self.client.command(command, params if params is not None else {}, request_id=request_id)

    def inspect(self, limit=200):
        return self.action("tree.snapshot", {"limit": limit})

    def expect(self, expectation):
        validate(expectation, ASSERTION, "expectation")
        validate_assertion(expectation, self.capabilities()["commands"])
        return {"satisfied": UI(self.client).check(expectation, wait=True)}

    def batch(self, steps, *, request_id=None):
        self.identify()
        return self.client.batch(steps, request_id=request_id)

    def run(self, workflow, output, *, inputs=None, screenshots=False):
        return replay(self.client, workflow, inputs if inputs is not None else {}, Path(output), screenshots)


class SessionGroup:
    def __init__(self, clients):
        self.clients = clients

    @classmethod
    def open(cls, path: Path):
        return cls(load_devices(path, minimum=1))

    def device(self, name):
        if name not in self.clients:
            raise ValueError("That device is outside the configured session group.")
        return LiveUI(self.clients[name])

    def sessions(self):
        def observe(name):
            try:
                identity = self.device(name).identify()
                return {"device": name, "target": identity["target"],
                        "seconds_remaining": identity["seconds_remaining"], "available": True}
            except ClientError as error:
                return {"device": name, "available": False, "http_status": error.status}

        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(observe, sorted(self.clients)))

    def coordinate(self, scenario, output, *, inputs=None):
        if len(self.clients) < 2:
            raise ValueError("A coordinated workflow needs at least two configured live devices.")
        return run_scenario(scenario, self.clients, inputs if inputs is not None else {}, Path(output))
