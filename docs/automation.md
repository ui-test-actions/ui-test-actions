# Agent automation API

An existing agent can use the HTTP API directly, the standard-library [Python client](../agent.py), or the browser controller. The agent runs on its current machine. The app, driver, and tunnel connector run in the GitHub job.

Use [agent-led UI exploration](exploration.md) to give the agent a test objective and run its decisions with deterministic, observed assertions.

Use [record and replay](record-replay.md) to turn actions from a live session or a passing exploration report into a parameterized workflow.

Use [multi-device orchestration](multi-device.md) to synchronize workflows and share test context across live sessions.

Use [performance measurements](performance.md) to collect startup, action timing, and native app process data.

Download the current job's `connection.json` and keep the private session token in a file on the agent host. Its URL is an HTTPS origin and its session ID identifies the intended runner. The command-line client checks that ID before making a request and refuses HTTP redirects.

```bash
python3 agent.py connection.json --token-file "$TOKEN_FILE" capabilities
python3 agent.py connection.json --token-file "$TOKEN_FILE" screenshot before.png
python3 agent.py connection.json --token-file "$TOKEN_FILE" action tree.snapshot
```

For a command with parameters, pass a UTF-8 JSON file. These commands focus a field at example coordinates and replace its contents. Set the coordinates from the current screenshot or focus a unique element with `element.click`.

```bash
printf '%s\n' '{"x":320,"y":200}' > click.json
printf '%s\n' '{"text":"مرحبًا بالعالم، ١٢٣؟ 🌍","replace":true}' > text.json
python3 agent.py connection.json --token-file "$TOKEN_FILE" action pointer.click --params-file click.json
python3 agent.py connection.json --token-file "$TOKEN_FILE" action text.insert --params-file text.json
python3 agent.py connection.json --token-file "$TOKEN_FILE" screenshot after.png
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

On desktop and the visible iOS Simulator, `replace: true` sends the platform select-all shortcut before pasting. Some controls bind that chord differently. The hosted X11 Tk Entry moved the insertion point instead of selecting the string. For that single-line control, `home`, `shift+end`, and `backspace` cleared the old text before insertion. Verify the actual result with a semantic assertion or copy-back after first setting the clipboard to a distinct test value.

### Elements and assertions

Use `tree.snapshot` for semantic state where exposed. A node may include a name, role, text, enabled and visible flags, parent ID, and bounding rectangle. Source availability depends on accessibility trust and on the app exposing the control. Password values are filtered when the native source identifies secure fields.

`element.find` matches all supplied selector properties. Match exact `role`, `name`, `text`, `resource_id`, `visible`, or `enabled`, use `text_contains` for a substring, or query native flags such as `properties: {"editable":true}`. Flags are driver-dependent. Use `snapshot_id` from the observation and `id` from the chosen node for `element.click`. The server re-observes the element before targeting its center and rejects a changed or ambiguous reference. Inspect screenshots for overlapping controls and coordinate-only surfaces.

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

Use the correct platform modifier, such as `command` on macOS and the visible iOS Simulator. An absence assertion fails when a truncated tree cannot establish absence. A batch validates every command and argument shape before applying any step. If an action then fails during execution, the batch stops and reports the completed count. Earlier steps remain applied. Capture fresh state before deciding how to recover. The wait timeout covers polling and may be exceeded by an individual native observation already in progress.

### Visual evidence

Use `visual.sample` for a reference frame or a rectangle of the screen. `visual.wait` compares that reference with the current image and reports average RGB channel difference on a reduced sample. Supply a region that excludes clocks, spinners, or unrelated UI. A stable condition requires remaining below the threshold for at least half a second. Use an app-specific assertion or inspect the resulting image to establish the intended change. A difference score alone only establishes pixel change.

Start recording with `recording.start`, drive the app, and call `recording.stop`. Download `/v2/recording` or use the Python client's recording command. Each recording is limited to 30 seconds at up to two frames per second. Captures can skip frames during a command. The GIF remains in memory and requires the session token. It is available only while the session is live.

### Gestures, apps, and files

Pointer coordinates are pixels measured from the top-left of the latest screenshot. The desktop driver provides pointer motion, click counts, hold, mouse buttons, scrolling, dragging, and native window commands. Android's default ADB driver uses single-touch events, with absolute orientation controls through `device.orientation`. The visible iOS Simulator has `device.rotate` for a relative quarter-turn and `pointer.pinch` for the Simulator's mirrored two-finger gesture. Place the cursor on one side of the simulator's gesture center and move out to spread or in to contract. Capture again after rotating. Use app-specific state to verify a gesture took effect.

Positive `pointer.scroll` offsets move through content to the right or down. Each backend converts the offsets into its native wheel or touch movement. Use short increments and check the resulting viewport when the item you need is off screen.

Appium provides `pointer.gesture` for synchronized touch tracks when configured. A touch track starts with a point at zero milliseconds. All tracks share the same sequence of segment durations.

On desktop, configure a fixed command for a process the session should own. This enables `app.status`, `app.launch`, `app.close`, and `app.restart` for that ID. Use an executable that stays associated with the app process. Capture current windows separately with `windows.list`; process exit alone does not establish that the app's UI is ready.

```yaml
desktop-apps: '{"test-app":{"argv":["/absolute/path/to/app","--test-mode"]}}'
```

Allowlist mobile app IDs in `app-ids` to use app launch, close, restart, reset, or uninstall where advertised. Use `app-installs` to map approved IDs to test package paths configured by the workflow. Clients request an ID. They do not supply a package path. Deep links are restricted to configured schemes. State-reset and uninstall operations are destructive to the test app's local data.

On desktops, enable `file-exchange: '1'` to stage base64 test files in a private temporary directory and read app-generated files back. The launch script receives `UI_TEST_EXCHANGE_DIR`. `files.list` returns the directory and plain names, `files.stage` creates a new file, and `files.read` returns bytes in base64. Use an ordinary UI action or a native file dialog to work with these files. Upload JSON is limited to 44,000 base64 characters. A download is limited to 128 KiB. The exchange accepts up to 24 entries and rejects traversal and linked files. Mobile device files are outside this desktop exchange.

### Recovery and concurrency

One driver operation controls a given runner at a time. Retry temporary `429 session_busy` responses with the same request ID, or wait for the active action to finish. Independent runner jobs have separate sessions and credentials. The latest 64 identified responses can be replayed within the same session. Reusing an ID with changed arguments returns `409 request_conflict`. When the replay window has passed, inspect the UI before retrying a mutation.

Operation failures include `unsupported_command`, `invalid_arguments`, `stale_snapshot`, `target_not_found`, `driver_timeout`, `condition_timeout`, and `assertion_failed`. A job expiry invalidates the credential and terminates the connector. Start a new job and get a fresh connection artifact when the session ends. The client cannot carry state or replay IDs between runners.

For delayed UI transitions, wait on a specific semantic or visual condition with a bounded timeout. For virtualized lists, observe current items, scroll in bounded steps, and re-resolve the item after each scroll. For dialogs and app permission prompts, first inspect the frontmost window or device image. Coordinate actions operate inside the current screenshot and cannot infer the intended UI element.

## Optional runner-local Appium

Supply `webdriver-url` and trusted `webdriver-capabilities` to use an Appium server started by the consumer workflow on the same runner. Bind Appium to loopback and install an appropriate driver. The connector routes only to this action's authenticated HTTP API. Appium's API and insecure extensions are outside the remote command contract. Keep insecure Appium server features disabled.

```yaml
webdriver-url: http://127.0.0.1:4723
webdriver-capabilities: >-
  {"platformName":"Android","appium:automationName":"UiAutomator2","appium:appPackage":"dev.example.TestApp"}
```

The action selects the same device for Appium, screenshots, and native helpers. The Appium adapter uses W3C touch input and the page source, then destroys its session at teardown. Startup depends on the Appium version, Xcode, and the test application. The hosted iOS setup uses a pinned prebuilt WebDriverAgent. It has verified semantic targeting, W3C gestures, and Unicode through the native Paste menu. Discover commands with `GET /v2/capabilities`. The default visible-Simulator backend exposes `text.insert` for direct entry. [Hosted iOS Appium setup and evidence](../verification/v2/ios-appium/) · [WebDriver routes](https://appium.io/docs/en/latest/reference/api/webdriver/) · [XCUITest driver](https://appium.github.io/appium-xcuitest-driver/latest/reference/capabilities/)

## Optional iOS Simulator accessibility

The native AXe mode exposes Simulator application elements and a screenshot in the same device coordinate space. It supports unique element targeting, text assertions, Unicode paste, hardware-key chords, and simulated scroll and drag. Use the visible Simulator mode for host dialogs and the Simulator's mirrored pinch gesture. The AXe view captures the simulated device display.

Install the pinned `AXe` executable and its bundled frameworks on the GitHub runner. Select an explicit device UDID, boot that simulator, open its Simulator window, install and launch the application, and wait for `axe describe-ui --udid "$UI_DEVICE"` to show the application. Attach the action by supplying `target: ios`, `device`, and the absolute `ios-axe-path`. Follow the hosted workflow for the tested action SHA, the release checksum, and the readiness approach. The agent still uses the same token, HTTPS connection artifact, and standard-library client. [Hosted workflow](../.github/workflows/ios-ax.yml) · [AXe release](https://github.com/cameroncooke/AXe/releases/tag/v2.1.1)

## Connection options

The default Quick Tunnel gives a temporary HTTPS address and uses the action's per-session bearer token. Its connector retries registration during startup. An exited Quick Tunnel creates a new address on a new run. Cloudflare sets no uptime guarantee and applies an in-flight request limit. [Quick Tunnel documentation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

For a fixed hostname, provision a dedicated remotely managed Cloudflare Tunnel. Set its service to `http://127.0.0.1:8787` and configure the action with `tunnel-hostname`, `origin-port` if different, and `tunnel-token: ${{ secrets.CLOUDFLARE_TUNNEL_TOKEN }}`. Serialize runs per hostname with GitHub workflow concurrency, since multiple connectors on the same hostname can route to different runners. The action attempts bounded restarts of an exited named connector during a live session. The connector token is passed through a private file and stays outside the app launch environment. Named Tunnel and Cloudflare Access are configured by the consumer and have local regression coverage. Their deployment requires real Cloudflare account configuration and an external acceptance check before relying on them.

Cloudflare Access is optional in front of a named tunnel. Automated clients can supply Access service-token headers in addition to the session bearer. The Python client accepts a private file containing `client_id` and `client_secret` with `--access-file`. Cloudflare terminates TLS on the edge. Run the action on dedicated GitHub-hosted test jobs with test data and least-privilege GitHub permissions. The authenticated desktop can operate any UI visible to that runner account. [Tunnel configuration](https://developers.cloudflare.com/tunnel/get-started/) · [Access service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)

## Operational checks

| Signal | Check |
| --- | --- |
| Connection artifact is missing | Inspect the app launch and readiness steps, selected emulator or simulator, then the tunnel registration message. A valid ready command should detect the state the agent needs. |
| The first screenshot is blank | Check for the expected foreground window or activity, and inspect the application's own startup log. In a Linux workflow, confirm its renderer can use the configured X display. |
| HTTP 401 | Check the private token file and the connection artifact for this run. Use a new token per session. |
| HTTP 429 from a command | Wait briefly and retry with the same request ID. Keep one writer per session. |
| HTTP 410 or Cloudflare 530 | Check the job status and remaining time. An expired or cancelled runner needs a fresh job. |
| Expected element is missing | Inspect a current screenshot and the source exposed by the platform. Check focus, popups, the viewport, and whether the relevant native framework exports that element. |
| Visual assertion misses a change | Capture the correct current rectangle. Use a deterministic region and pair the pixel observation with an app-specific check. |

## Development and releases

The composite action starts the loopback listener and publishes connection metadata, then its hold step renews a short lease while the job is alive. The session owns request authentication, expiry, and driver serialization. The automation layer handles schemas, replay, visual evidence, and selectors. The platform adapters translate typed operations into native events. Keep the action bearer and any Cloudflare credentials in their separate trust boundaries.

The gesture adapter uses WebDriver's synchronized action ticks. The agent workflow adopts explicit wait conditions and re-observation before targeting a control. Accessible bounds can still be obscured by a transient dialog, so pair native element assertions with the screenshot where focus or overlapping UI matters. [WebDriver actions](https://www.w3.org/TR/webdriver2/#actions) · [Playwright actionability checks](https://playwright.dev/docs/actionability)

Run the same portable tests as the hosted regression workflow before changing the action pin.

```bash
python3 -m pip install Pillow==12.2.0
python3 -m unittest discover -s tests -v
```

The normal pull-request checks run across Windows, macOS, and Linux. Emulator, simulator, upstream application, and timed-session workflows run on demand. Reuse verified upstream binaries when available and verify their content hashes. The release pin is a full action commit shown in the consumer examples. Publish a new pin when its supported targets have external checks and retained observations. Preserve existing endpoint behavior within its API version and evolve optional operations through capability discovery. [CI workflow](../.github/workflows/tests.yml) · [Hosted evidence](../verification/v2/README.md)
