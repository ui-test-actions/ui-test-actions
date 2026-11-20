# Hosted command coverage

Use the evidence links in the [verification report](README.md) for run IDs and backend versions. A command listed as observed produced an app, device, or runner result that the external client checked. Within a command, evidence applies to the tested arguments, app controls, and runtime. The live capabilities endpoint is authoritative for availability.

| API | Windows | macOS | Linux | Android | iOS visible Simulator |
| --- | --- | --- | --- | --- | --- |
| `GET /v1/session`, `GET /v2/capabilities` | Observed | Observed | Observed | Observed | Observed |
| `GET /v1/screenshot` | Observed | Observed | Observed | Observed | Observed |
| `POST /v1/input` | v1 compatibility proof | v1 compatibility proof | v1 compatibility proof | v1 compatibility proof | v1 compatibility proof |
| `pointer.move` | Native hover event | Native hover event | Native hover event | Unavailable | Offered for host pointer |
| `pointer.click` | Click, double, hold, right | Click, double, hold, right | Click, double, hold, right | Tap and double tap | Tap |
| `pointer.drag` | Native drop in fixture | Native drop in fixture | Native drop in fixture | Notification shade and app swipe | App list swipe |
| `pointer.scroll` | Native scroll event | Native scroll event | Native scroll event | App list movement | Simulator's host scrolling offered |
| `pointer.pinch` | Unavailable | Unavailable | Unavailable | Use Appium `pointer.gesture` | Expansion and contraction |
| `pointer.gesture` | Unavailable | Unavailable | Unavailable | Two synchronized tracks with optional UiAutomator2 | Arbitrary tracks unverified on Appium XCUITest |
| `keyboard.press` | Save and F6 | Save and F6 | Save, F6, selection, and deletion | Selection and copy/paste shortcuts | Copy/paste and app search |
| `text.insert` | Native document persistence | Native document persistence | Qt and GTK persistence, explicit Tk selection | Native editor persistence | SwiftUI note persistence |
| `clipboard.set`, `clipboard.get` | Exact Unicode | Exact Unicode | Exact Unicode on X11 | Exact Unicode | Exact Unicode |
| `windows.list`, `windows.focus`, `windows.move_resize`, `windows.close` | Observed app-owned detail window | Observed app-owned detail window | Observed app-owned detail window | Unavailable | Unavailable |
| `tree.snapshot`, `element.find` | Hosted Notepad++ UIA | Hosted CotEditor AX | Mousepad AT-SPI | Markor | Unavailable in the default backend |
| `element.click` | Native UIA geometry offered | Native AX geometry offered | Mousepad editor and Save command | Markor and Android native fixture | Unavailable in the default backend |
| `element.assert`, `element.wait` | Native UIA source offered | Native AX source offered | Exact accessible Mousepad text | Native state and stale reference cases | Unavailable in the default backend |
| `visual.sample`, `visual.wait` | Observed app-region change | Observed app-region change | Observed app-region change | Verified changed frame | Screenshots and recordings verified. Visual polling available |
| `recording.start`, `recording.stop`, `GET /v2/recording` | GIF frames observed | GIF frames observed | GIF frames observed | GIF frames observed | GIF frames observed |
| `files.list`, `files.stage`, `files.read` | Optional exchange round-trip | Optional exchange round-trip | Optional exchange round-trip and file chooser | Unavailable | Unavailable |
| `app.status`, `app.launch`, `app.close`, `app.restart` | Managed process, crash, and relaunch | Managed process, crash, and relaunch | Managed process, crash, and relaunch | Launch, close, restart. No process status | Launch, close, restart. No process status |
| `app.reset`, `app.install`, `app.uninstall` | Unavailable | Unavailable | Unavailable | Allowlisted test package | Allowlisted simulator package |
| `app.deeplink` | Unavailable | Unavailable | Unavailable | Native fixture handler | Native fixture handler after confirmation |
| `device.orientation` | Unavailable | Unavailable | Unavailable | Rotate and restore | Use relative rotation |
| `device.rotate` | Unavailable | Unavailable | Unavailable | Use absolute orientation | Rotate and restore |
| `POST /v2/batch` | Three-step replay and desktop contract | Three-step replay and desktop contract | Three-step replay and desktop contract | Three-step replay | Three-step replay |

The fast regression suite exercises invalid Unicode, schema and content-size errors, stale references, controlled request interruption, replay cache limits, concurrent writes, clipboard native formats, file quota recovery, expired authentication, and lost job heartbeat. The hosted runs cover normal and cancelled endpoint teardown, cross-session credentials, parallel jobs, and a bounded read burst. Full network fault injection, device hardware, extensive DPI permutations, and very long stress ramps have no hosted evidence here.
