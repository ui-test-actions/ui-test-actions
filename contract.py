"""Versioned command schemas and validation for agent clients."""

import re
from urllib.parse import urlsplit


class CommandError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def obj(required=(), **properties):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def integer(low, high):
    return {"type": "integer", "minimum": low, "maximum": high}


def string(limit, minimum=1, pattern=None):
    schema = {"type": "string", "minLength": minimum, "maxLength": limit}
    if pattern:
        schema["pattern"] = pattern
    return schema


def choice(*values):
    return {"type": "string", "enum": list(values)}


BOOLEAN = {"type": "boolean"}
COORD = integer(0, 16383)
SIZE = integer(1, 16384)
XY = {"x": COORD, "y": COORD}
END = {"end_x": COORD, "end_y": COORD}
TIME = integer(0, 3000)
TEXT = string(8192, 0)
IDENTIFIER = string(256)
BUTTON = choice("left", "middle", "right")
RECT = obj(("x", "y", "width", "height"), **XY, width=SIZE, height=SIZE)
SELECTOR = obj(id=IDENTIFIER, role=IDENTIFIER, name=string(512), text=string(512), text_contains=string(512),
               resource_id=IDENTIFIER, enabled=BOOLEAN, visible=BOOLEAN)
REQUEST_ID = string(64, 1, r"^[a-zA-Z0-9_.-]+$")
APP_ID = string(255, 1, r"^[a-zA-Z0-9_.-]+$")

FILE_NAME = string(100, 1, r"[a-zA-Z0-9][a-zA-Z0-9_.-]*")

TOUCH_POINT = obj(("x", "y", "duration_ms"), **XY, duration_ms=TIME)
TRACK = {"type": "array", "minItems": 2, "maxItems": 12, "items": TOUCH_POINT}

COMMANDS = {
    "pointer.gesture": obj(("tracks",), tracks={"type": "array", "minItems": 1, "maxItems": 5, "items": TRACK}),
    "files.list": obj(),
    "files.stage": obj(("name", "base64"), name=FILE_NAME, base64=string(44000, 0)),
    "files.read": obj(("name",), name=FILE_NAME),
    "pointer.move": obj(("x", "y"), **XY, duration_ms=TIME),
    "pointer.click": obj(("x", "y"), **XY, button=BUTTON, count=integer(1, 3), hold_ms=TIME),
    "pointer.drag": obj(("x", "y", "end_x", "end_y"), **XY, **END, button=BUTTON, duration_ms=TIME),
    "pointer.scroll": obj(("x", "y"), **XY, dx=integer(-30, 30), dy=integer(-30, 30)),
    "keyboard.press": obj(("keys",), keys={"type": "array", "minItems": 1, "maxItems": 5,
                                          "items": string(24, 1, r"^[a-zA-Z0-9_+-]+$")}),
    "text.insert": obj(("text",), text=TEXT, replace=BOOLEAN),
    "clipboard.get": obj(),
    "clipboard.set": obj(("text",), text=TEXT),
    "windows.list": obj(),
    "windows.focus": obj(("id",), id=IDENTIFIER),
    "windows.move_resize": obj(("id", "x", "y", "width", "height"), id=IDENTIFIER,
                               x=integer(-16384, 16383), y=integer(-16384, 16383), width=SIZE, height=SIZE),
    "windows.close": obj(("id",), id=IDENTIFIER),
    "tree.snapshot": obj(),
    "element.find": obj(("selector",), selector=SELECTOR),
    "element.click": obj(("id", "snapshot_id"), id=IDENTIFIER, snapshot_id=IDENTIFIER),
    "element.assert": obj(("selector", "state"), selector=SELECTOR, state=choice("present", "absent")),
    "element.wait": obj(("selector", "state"), selector=SELECTOR, state=choice("present", "absent"),
                        timeout_ms=integer(100, 10000)),
    "recording.start": obj(duration_seconds=integer(2, 30)),
    "recording.stop": obj(),
    "visual.sample": obj(region=RECT),
    "visual.wait": obj(("baseline",), baseline=IDENTIFIER, condition=choice("changed", "stable"),
                       threshold=integer(1, 255), timeout_ms=integer(100, 10000)),
    "app.status": obj(("id",), id=APP_ID),
    "app.launch": obj(("id",), id=APP_ID),
    "app.close": obj(("id",), id=APP_ID),
    "app.restart": obj(("id",), id=APP_ID),
    "app.reset": obj(("id",), id=APP_ID),
    "app.uninstall": obj(("id",), id=APP_ID),
    "app.install": obj(("id",), id=APP_ID),
    "app.deeplink": obj(("url",), id=APP_ID, url=string(4096)),
    "device.orientation": obj(("orientation",), orientation=choice("portrait", "landscape", "reverse_portrait",
                                                                     "reverse_landscape", "auto")),
}
OPERATION = obj(("command",), command=string(64), params={"type": "object"})
OPERATION_REQUEST = obj(("command",), request_id=REQUEST_ID, **OPERATION["properties"])
BATCH_REQUEST = obj(("steps",), request_id=REQUEST_ID,
                    steps={"type": "array", "minItems": 1, "maxItems": 12, "items": OPERATION})


def validate(value, schema, label):
    kind = schema["type"]
    if kind == "object" and type(value) is dict:
        fields = schema.get("properties")
        if fields is None:
            return
        if any(field not in value for field in schema["required"]):
            raise CommandError("invalid_arguments", f"{label} is missing a required field.")
        if value.keys() - fields.keys():
            raise CommandError("invalid_arguments", f"{label} contains an unknown field.")
        for key, item in value.items():
            validate(item, fields[key], f"{label}.{key}")
    elif kind == "array" and type(value) is list:
        if not schema["minItems"] <= len(value) <= schema["maxItems"]:
            raise CommandError("invalid_arguments", f"{label} has an invalid number of items.")
        for item in value:
            validate(item, schema["items"], f"{label} item")
    elif kind == "integer" and type(value) is int:
        if not schema["minimum"] <= value <= schema["maximum"]:
            raise CommandError("invalid_arguments", f"{label} is out of range.")
    elif kind == "string" and type(value) is str:
        if "enum" in schema and value not in schema["enum"]:
            raise CommandError("invalid_arguments", f"{label} is not an allowed value.")
        if "minLength" in schema and not schema["minLength"] <= len(value) <= schema["maxLength"]:
            raise CommandError("invalid_arguments", f"{label} has an invalid length.")
        if "\x00" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise CommandError("invalid_arguments", f"{label} contains an invalid Unicode character.")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise CommandError("invalid_arguments", f"{label} has an invalid format.")
    elif kind != "boolean" or type(value) is not bool:
        raise CommandError("invalid_arguments", f"{label} must be a JSON {kind}.")


def validate_operation(operation, commands):
    command = operation["command"]
    if command not in COMMANDS:
        raise CommandError("unknown_command", "The command is not defined.", 404)
    if command not in commands:
        raise CommandError("unsupported_command", "The active driver does not provide this command.", 422)
    params = operation.get("params", {})
    validate(params, COMMANDS[command], "params")
    if "selector" in params and not params["selector"]:
        raise CommandError("invalid_arguments", "Provide at least one selector property.")
    if command == "pointer.scroll" and not (params.get("dx") or params.get("dy")):
        raise CommandError("invalid_arguments", "Provide a nonzero scroll amount.")
    if command == "app.deeplink":
        try:
            uri = urlsplit(params["url"])
        except ValueError:
            raise CommandError("invalid_arguments", "Provide a valid deep link.") from None
        if uri.scheme in ("", "file", "data", "javascript", "intent", "about") or any(
            ord(char) <= 32 or ord(char) == 127 for char in params["url"]
        ):
            raise CommandError("invalid_arguments", "Provide a supported application deep link.")
    return command, params
