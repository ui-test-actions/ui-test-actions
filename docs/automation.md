# Agent automation API

An existing agent can use the HTTP API directly, the standard-library [Python client](../agent.py), or the browser controller. The agent runs on its current machine. The app, driver, and tunnel connector run in the GitHub job.

Download the current job's `connection.json` and keep the private session token in a file on the agent host. Its URL is an HTTPS origin and its session ID identifies the intended runner. The command-line client checks that ID before making a request and refuses HTTP redirects.

```bash
python3 agent.py connection.json --token-file "$TOKEN_FILE" capabilities
python3 agent.py connection.json --token-file "$TOKEN_FILE" screenshot before.png
python3 agent.py connection.json --token-file "$TOKEN_FILE" action tree.snapshot
```

## Inspect, act, and verify

| Request | Result |
| --- | --- |
| `GET /v1/session` | Session ID, target, and seconds remaining. |
| `GET /v1/screenshot` | PNG of the current display or native device viewport. |
| `GET /v2/capabilities` | Active target, display dimensions, limits, and JSON parameter schemas for the commands the driver offers. |
| `POST /v2/action` | One command with a structured success or error. |
| `POST /v2/batch` | Up to 12 ordered commands with a result for each attempted step. |
| `GET /v2/recording` | The latest finished, session-private GIF recording. |

Send the bearer token in the authorization header. Use JSON request bodies encoded as UTF-8. A command request has a name and optional parameters and request ID.

```json
{
  "request_id": "change-note-1",
  "command": "text.insert",
  "params": {
    "text": "مرحبًا بالعالم، ١٢٣؟\nMixed English and العربية 🌍",
    "replace": true
  }
}
```

Focus the editable control before inserting text. On desktop, the driver writes native Unicode clipboard data and uses the host paste shortcut. On Android, a temporary test input method commits Unicode to the focused application and uses the device clipboard. On the visible iOS Simulator, the driver writes that simulator's pasteboard and pastes into the focused control. The app determines shaping, bidirectional layout, selection semantics, normalization, and what a field accepts. A single-line field may remove line breaks. The existing `/v1/input` text contract remains ASCII for compatibility.

### Elements and assertions

Use `tree.snapshot` for semantic state where exposed. A node may include a name, role, text, enabled and visible flags, parent ID, and bounding rectangle. Source availability depends on accessibility trust and on the app exposing the control. Password values are filtered when the native source identifies secure fields.

`element.find` matches any conjunction of exact selector properties and optional `text_contains`. Use a fresh unique snapshot reference for `element.click`. The server re-observes the element before targeting its center and rejects a changed or ambiguous reference. Inspect screenshots for overlapping controls and coordinate-only surfaces.

```json
{
  "steps": [
    {"command":"element.wait","params":{"selector":{"name":"Save","visible":true,"enabled":true},"state":"present","timeout_ms":4000}},
    {"command":"keyboard.press","params":{"keys":["ctrl","s"]}},
    {"command":"element.assert","params":{"selector":{"name":"Unsaved changes"},"state":"absent"}}
  ],
  "request_id":"save-note-1"
}
```

Use the correct platform modifier, such as `command` on macOS. An absence assertion fails when a truncated tree cannot establish absence. A batch stops at the first failed action and returns the number of completed steps. Earlier steps remain applied. Capture fresh state before deciding how to recover. The wait timeout covers polling and may be exceeded by an individual native observation already in progress.

### Visual evidence

Use `visual.sample` for a reference frame or a rectangle of the screen. `visual.wait` compares that reference with the current image and reports average RGB channel difference on a reduced sample. Supply a region that excludes clocks, spinners, or unrelated UI. A stable condition requires remaining below the threshold for at least half a second. Use an app-specific assertion or inspect the resulting image to establish the intended change. A difference score alone only establishes pixel change.

Start recording with `recording.start`, drive the app, and call `recording.stop`. Download `/v2/recording` or use the Python client's recording command. Each recording is limited to 30 seconds at up to two frames per second. Captures can skip frames during a command. The GIF remains in memory and requires the session token. It is available only while the session is live.

### Gestures, apps, and files

Pointer coordinates are pixels measured from the top-left of the latest screenshot. The desktop driver supports pointer motion, click counts, hold, mouse buttons, scrolling, dragging, and native window operations. Android's default ADB driver uses single-touch events. Appium can supply multiple synchronized touch tracks when explicitly configured. A touch track starts with a point at zero milliseconds. All tracks share the same sequence of segment durations.

Allowlist mobile app IDs in `app-ids` to use app launch, close, restart, reset, or uninstall where advertised. Use `app-installs` to map approved IDs to test package paths configured by the workflow. Clients request an ID. They do not supply a package path. Deep links are restricted to configured schemes. State-reset and uninstall operations are destructive to the test app's local data.

On desktops, enable `file-exchange: '1'` to stage base64 test files in a private temporary directory and read app-generated files back. The launch script receives `UI_TEST_EXCHANGE_DIR`. `files.list` returns the directory and plain names, `files.stage` creates a new file, and `files.read` returns bytes in base64. Use an ordinary UI action or a native file dialog to work with these files. Upload JSON is limited to 44,000 base64 characters. A download is limited to 128 KiB. The exchange accepts up to 24 entries and rejects traversal and linked files. Mobile device files are outside this desktop exchange.

### Recovery and concurrency

One driver operation controls a given runner at a time. Retry temporary `429 session_busy` responses with the same request ID, or wait for the active action to finish. Independent runner jobs have separate sessions and credentials. The latest 64 identified responses can be replayed within the same session. Reusing an ID with changed arguments returns `409 request_conflict`. When the replay window has passed, inspect the UI before retrying a mutation.

Operation failures include `unsupported_command`, `invalid_arguments`, `stale_snapshot`, `target_not_found`, `driver_timeout`, `condition_timeout`, and `assertion_failed`. A job expiry invalidates the credential and terminates the connector. Start a new job and get a fresh connection artifact when the session ends. The client cannot carry state or replay IDs between runners.

## Optional runner-local Appium

Supply `webdriver-url` and trusted `webdriver-capabilities` to use an Appium server started by the consumer workflow on the same runner. Bind Appium to loopback and install an appropriate driver. The connector routes only to this action's authenticated HTTP API. Appium's API and insecure extensions are outside the remote command contract. Keep insecure Appium server features disabled.

```yaml
webdriver-url: http://127.0.0.1:4723
webdriver-capabilities: >-
  {"platformName":"iOS","appium:automationName":"XCUITest","appium:bundleId":"dev.example.TestApp"}
```

The action selects the same device for Appium, screenshots, and native helpers. The Appium adapter uses W3C touch input and the page source, then destroys its session at teardown. Startup depends on the Appium version, Xcode, and the test application. See the verification report for the hosted status of this opt-in path. [WebDriver routes](https://appium.io/docs/en/latest/reference/api/webdriver/) · [XCUITest driver](https://appium.github.io/appium-xcuitest-driver/latest/reference/capabilities/)

## Connection options

The default Quick Tunnel gives a temporary HTTPS address and uses the action's per-session bearer token. Its connector retries registration during startup. An exited Quick Tunnel creates a new address on a new run. Cloudflare sets no uptime guarantee and applies an in-flight request limit. [Quick Tunnel documentation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

For a fixed hostname, provision a dedicated remotely managed Cloudflare Tunnel. Set its service to `http://127.0.0.1:8787` and configure the action with `tunnel-hostname`, `origin-port` if different, and `tunnel-token: ${{ secrets.CLOUDFLARE_TUNNEL_TOKEN }}`. Serialize runs per hostname with GitHub workflow concurrency, since multiple connectors on the same hostname can route to different runners. The action attempts bounded restarts of an exited named connector during a live session. The connector token is passed through a private file and stays outside the app launch environment.

Cloudflare Access is optional in front of a named tunnel. Automated clients can supply Access service-token headers in addition to the session bearer. The Python client accepts a private file containing `client_id` and `client_secret` with `--access-file`. Cloudflare terminates TLS on the edge. Run the action on dedicated GitHub-hosted test jobs with test data and least-privilege GitHub permissions. The authenticated desktop can operate any UI visible to that runner account. [Tunnel configuration](https://developers.cloudflare.com/tunnel/get-started/) · [Access service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
