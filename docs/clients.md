# Connect a CLI, SDK, or MCP client

Use the same private connection artifacts and bearer-token files as the basic client. Give each live device a unique name in a local session registry. Values are paths relative to the registry or absolute paths. A device can also specify an optional `access_file` for Cloudflare Access.

```json
{
  "android": {"connection": "android/connection.json", "token_file": "android.token"},
  "ios": {"connection": "ios/connection.json", "token_file": "ios.token"}
}
```

The registry supports one through eight sessions. Replace expired files and start a fresh client using the new registry. The client checks each live connection against the session ID from its artifact. Always use the capability schema returned by that runner. [Create and download session artifacts](../README.md#connect-and-hand-the-session-to-an-agent)

## Command line

```bash
python3 ui.py --sessions sessions.json sessions
python3 ui.py --sessions sessions.json capabilities android
python3 ui.py --sessions sessions.json inspect android --limit 100
python3 ui.py --sessions sessions.json screenshot android screen.png
python3 ui.py --sessions sessions.json action android pointer.click --params tap.json
python3 ui.py --sessions sessions.json assert android expected.json
python3 ui.py --sessions sessions.json workflow android journey.yaml --output results
python3 ui.py --sessions sessions.json coordinate pair.json --output pair-results
```

Commands emit JSON and return a nonzero code for failed actions or assertions. Use `--request-id` on a retried action or batch to preserve its replay identity. Batch input is a JSON object with a `steps` array. The assert command accepts an [element or pixel expectation](record-replay.md). The coordinated workflow format and capture types remain the same as in [multi-device orchestration](multi-device.md).

## Python SDK

```python
from pathlib import Path
from ui_sdk import SessionGroup

group = SessionGroup.open(Path("sessions.json"))
android = group.device("android")
print(group.sessions())
print(android.capabilities()["commands"])
print(android.inspect(limit=100))
Path("screen.png").write_bytes(android.screenshot())
```

`LiveUI.open` also accepts individual connection, token-file, and optional Access-file paths. Use `action`, `batch`, `expect`, and `run` on a live device or `coordinate` on the group. These methods share the same HTTPS client and workflow engine as the existing command-line tools. Runner rejections expose the HTTP status and structured response.

## MCP for an existing agent

Configure the agent to launch this local subprocess with stdio. Use absolute paths for the script and registry in the host configuration. The process uses Python's standard library for transport. Pixel assertions also use Pillow on the machine running the MCP process.

```json
{
  "command": "python3",
  "args": [
    "/path/to/ui-test-actions/mcp_server.py",
    "--sessions", "/private/sessions.json",
    "--output-root", "/private/ui-evidence"
  ]
}
```

Start with `ui_sessions` and `ui_capabilities`. Use `ui_inspect` for a native tree or `ui_screenshot` for an image. Send one command through `ui_action`, or use `ui_batch`, `ui_assert`, `ui_workflow`, and `ui_coordinate`. An action returns a structured result or a tool error with an HTTP status and driver code when available. Tool calls select only configured device names. Replay files and screenshots go to the local client. MCP starts no listener and sends no session secret to the agent as a tool result.

This adapter negotiates the 2025-11-25, 2025-06-18, and 2025-03-26 MCP revisions over stdio. The reported verification covers the negotiated 2025-11-25 revision. [MCP stdio specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

## TypeScript SDK

Use Node 24 with the same Python runtime and paths. The TypeScript SDK launches the same stdio backend so command semantics, assertions, and multi-device coordination all use the shared engine.

```bash
node examples/sdk.ts sessions.json android screen.png
```

```ts
import { UiTestClient } from "./sdk/typescript/index.ts"

const client = await UiTestClient.open({ sessions: "sessions.json", server: "mcp_server.py" })
try {
  console.log(await client.sessions())
  console.log(await client.capabilities("android"))
  await client.assert("android", { element: { selector: { text: "Connected" }, state: "present" } })
} finally {
  client.close()
}
```

The TypeScript methods return typed live-device information, binary PNGs, structured command results, and `UiError` details. Configure `timeoutMs` for a longer workflow. A timed-out caller can query the live state and reuse an action request ID before trying again.

The external verification used the official Python MCP SDK 1.30.0 and Node 24.20 against the published action pin `b57a9501805d6b75f94c6fa7ac1df4e37726a959`. It verified the live fixture transition through MCP on Linux and through the TypeScript SDK on Windows. The Python SDK and CLI observed both sessions, and a coordinated scenario read back exact mixed Arabic text from both clipboards. An unknown action returned a structured 404. [Linux run 44762120952](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44762120952) · [Windows run 44762129782](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44762129782) · [Evidence](../verification/sdk/)
