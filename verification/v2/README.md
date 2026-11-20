# v2 hosted verification

The external clients used the repository-qualified action and the same authenticated connection artifact a consumer job receives. Each real app wrote its own data. A later GitHub job step independently checked the saved text or the simulator app's note vault. Tests used synthetic documents containing Arabic, Arabic-Indic numerals, Arabic punctuation, English, accented Latin, emoji, and line breaks. The four desktop and Android document checks allow a UTF-8 BOM, conventional platform line endings, and one trailing newline. The iOS assertion matched the exact Unicode title and body in one active, non-sample note.

## Immutable candidate

The desktop, Android, and iOS consumer examples reference `803d83d50713f845db414c30c7c826071ede907c`. An external client discovered the API, entered mixed Arabic and English text into each fixture, applied it, and asserted the expected blue-to-green transition. A fresh client observed the same live session and resulting screen. Anonymous session requests returned HTTP 401. Replaying the same batch ID returned the original response. The before-and-after images show the actual applied text. [Candidate commit](https://github.com/ui-test-actions/ui-test-actions/commit/803d83d50713f845db414c30c7c826071ede907c)

| Target | Workflow at the exact action ref | External evidence |
| --- | --- | --- |
| Linux | [Ubuntu 24.04](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44688735749) | [Before, after, and assertions](candidate/linux/) |
| Windows | [Windows Server 2025](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44688735537) | [Before, after, and assertions](candidate/windows/) |
| macOS | [macOS 15](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44688735459) | [Before, after, and assertions](candidate/macos/) |
| Android | [Android 35 emulator](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44688735408) | [Before, after, and assertions](candidate/android/) |
| iOS | [iPhone 17 Pro, iOS 26.2](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44688735152) | [Before, after, and assertions](candidate/ios/) |

The fixture proof is reproducible using [probe_fixture.py](../probe_fixture.py) on the external machine with Pillow. Supply the connection file, private token file, evidence directory, and the coordinates from the current screenshot. Use `--dismiss` only if a startup dialog is visible. The regular agent CLI has no Pillow dependency. [Fast compatibility tests at the candidate](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44688269102) · [45-test follow-up on Windows, macOS, and Linux](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44689292574)

All five jobs reported normal closure. Each old URL returned HTTP 530 with its valid bearer, and the raw bearer was absent from its GitHub log and connection artifact. A distinct Windows job returned HTTP 401 for another live session's bearer and for a missing bearer, then stopped accepting its own bearer 8.43 seconds after cancellation was submitted. [Closure checks](candidate/closure.json) · [Cancellation trace](candidate/cancellation.json) · [GitHub cancellation run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44690408070)

## Real applications

| Target | App | Checked outcome | GitHub run and evidence |
| --- | --- | --- | --- |
| Windows | Notepad++, Win32 and Scintilla | UI Automation found the editor. Clipboard, text replacement, and Ctrl+S preserved the exact text. | [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44683919225) · [Evidence](windows/) |
| macOS | CotEditor, AppKit and SwiftUI | AX found the editor and returned the text. Native window resize and focus changed actual bounds. Paste, copy, and save preserved the exact text. | [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44684822788) · [Evidence](macos/) · [Earlier native dialog run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44683446564) |
| Linux | Notepad Next, Qt and Scintilla | Clipboard, replacement, native file selection, context menu, resize, and save. Exact text passed persistence and copy-back. | [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685999727) · [Evidence](linux/) |
| Linux | Mousepad, GTK and GtkSourceView | Arabic-localized menus and mixed-direction text. AT-SPI found the editable node, returned the exact multiline text, and invoked the visible Save menu item. The native chooser opened a staged file whose exact contents appeared in the editor. | [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44689388056) · [Evidence](gtk/) |
| Android | Markor, AndroidX native editor and WebView | Granted storage through the visible permission UI, edited with the native test IME, saved and reopened the document, inspected both editor and preview, and verified exact text. | [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44683446672) · [Evidence](android/) |
| iOS | Thought Meadow, SwiftUI | Entered Arabic and mixed Unicode into a real note, switched to Markdown preview, and filtered the saved note with an Arabic query. | [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44683446537) · [Evidence](ios/) |

[Exact upstream commits, releases, hashes, and licenses](../real-apps/apps.json) · [Reproduction instructions](../real-apps/README.md)

Notepad Next returned an empty AT-SPI observation in the hosted Qt AppImage. It preserved the full file and clipboard content but displayed only one of the three lines correctly in the captured editing view. Mousepad rendered the tested Arabic-leading lines right aligned and provided the document text through AT-SPI. The Thought Meadow screenshots show Arabic editing, preview, and search results. Physical Arabic keyboard layout, composition, font coverage, cursor movement across bidirectional text, and selection behavior vary by app and need separate acceptance tests. [Mousepad 0.6.1 source](https://gitlab.xfce.org/apps/mousepad/-/commit/c4b2fcbba98a853cac1998269c55b3b954e3faf0)

## Tool and lifecycle checks

| Check | Hosted runs and evidence |
| --- | --- |
| Desktop file staging and download, byte equality, duplicate filename and traversal rejection, batch replay, visual change, GIF capture, and 24 parallel reads per runner | [Linux](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685158477) · [Windows](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685164353) · [macOS](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685170390) · [Evidence](desktop-contract/) |
| Native hover, double-click, right-click menu and menu item, press-and-hold, drag, scroll, hardware shortcut, exact multiline Unicode, and window focus, resize, and close | [Linux](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44691101587) · [Windows](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44691101596) · [macOS](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44691101607) · [Screenshots and application event logs](desktop-native/) |
| Real desktop process exit code 17, visual disappearance, relaunch, and allowlist enforcement | [Linux](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44686096299) · [Windows](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44686102819) · [macOS](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44686109493) · [Evidence](process-recovery/) |
| Test app close, launch, restart, reset, uninstall, reinstall, and rejection of unrelated app IDs | [Android](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685177176) · [iOS](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685183256) · [Evidence](mobile-lifecycle/) |
| Android rotation, native selection and clipboard shortcuts, semantic wait and stale-ref rejection, native notification shade, recording, reconnect, and authentication | [Markor run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44683446672) · [Evidence](android/) |
| Android synchronized two-finger expansion and contraction, semantic state assertions, and an allowlisted deep link | [UiAutomator2 run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44687379513) · [Evidence](android-native/) |
| iOS visible Simulator pinch expansion and contraction, landscape rotation, and deep link through the native confirmation prompt | [Simulator run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44687131923) · [Evidence](ios-gestures/) |
| External agent using the documented Python client and browser using the Unicode controller | [iOS agent run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44683446537) · [Linux browser evidence](desktop-contract/linux/browser-arabic.png) |

The Windows recovery run was intentionally cancelled after its process checks. An independent Linux session's token and a missing bearer each returned HTTP 401 on Windows. The Windows session's own token returned HTTP 200 before cancellation and HTTP 530 about eight seconds after the cancellation request. Normal expiry was checked on separate successful workflow runs. [Cancellation trace](process-recovery/windows/cancellation.json)

The first v2 Linux session ran for 60 minutes and 0.797 seconds between the runner's ready and closed log entries. A fresh client changed the Tk fixture's visible label during the last minute. The Tk entry kept earlier text because its X11 shortcut and paste semantics differ. The HTTPS endpoint returned 530 around the deadline. The runner and external clocks differed by roughly ten seconds, so compare actual session time with the runner's monotonic timer and use `seconds_remaining` during live observation. [Runner](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685158477) · [Hour trace and screenshots](hour-initial/)

App screenshots may be cropped to the display or window containing the test. Connection artifacts and raw bearer values are excluded from this directory.

## Capability coverage

**Verified** means an external hosted run produced an observable result. **Partial** means the driver offers a relevant operation, but the hosted evidence covers only certain controls, options, or apps. **Unavailable** means the default driver has no operation for that capability. Query `GET /v2/capabilities` for the actual session, including optional features enabled by the workflow.

| Capability | Windows | macOS | Linux | Android | iOS |
| --- | --- | --- | --- | --- | --- |
| Live screenshots, input, Unicode replacement, and observable state change | Verified | Verified | Verified | Verified | Verified |
| Unicode clipboard, multiline persistence, mixed RTL and LTR content | Verified | Verified | Verified on GTK and Qt with different rendering | Verified | Verified |
| General Arabic hardware-keyboard input, composition, and precise bidirectional caret control | Partial | Partial | Partial | Partial | Partial |
| Click/tap, shortcuts, scrolling, dragging, and context actions | Partial across all gesture options | Partial across all gesture options | Partial across all gesture options | Partial with native single-touch and selected shortcuts | Partial with Simulator gestures and selected shortcuts |
| Native semantics, unique element selection, and assertions | Verified on the tested Win32 app. Other providers vary | Verified on the tested AppKit app. Other providers vary | Verified on GTK. Unavailable in the tested Qt build | Verified in Markor | Visual assertions on the default backend |
| Multi-finger input | Unavailable | Unavailable | Unavailable | Verified with optional Appium UiAutomator2 | Verified for visible Simulator pinch. Arbitrary touch tracks remain unverified |
| Window list, focus, move/resize, and close | Verified with the hosted detail window | Verified with the hosted detail window | Verified with the hosted detail window | Unavailable as desktop window operations | Simulator host window only |
| Managed app lifecycle and restart | Verified owned process | Verified owned process | Verified owned process | Verified allowlisted package | Verified allowlisted simulator bundle |
| Rotating display/device | Desktop resize only | Desktop resize only | Desktop resize and configurable virtual display | Verified portrait and landscape | Verified relative rotation |
| Native file dialogs and file exchange | Verified desktop exchange. Native UI coverage is partial | Verified desktop exchange and native dialog | Verified desktop exchange and native open dialog | Native app file and permission UI. Generalized transfer is unavailable | App-driven file UI. Generalized transfer is unavailable |
| GIF recording and visual comparison | Verified | Verified | Verified | Verified recording. Partial visual cases | Verified recording. Partial visual cases |
| Batch replay, fresh-client reconnect, anonymous rejection | Verified | Verified | Verified | Verified | Verified |

Coverage includes Win32/Scintilla, AppKit/SwiftUI, GTK, Qt/Scintilla, AndroidX and WebView, and SwiftUI/UIKit. Electron, Flutter, Compose Multiplatform, Wayland, real mobile devices, locale-specific hardware keyboard layouts, browser DOM inspection, system notifications beyond the observed Android shade, and a full DPI or display compatibility matrix have no acceptance evidence here.

The portable regressions cover structured invalid input, replay conflicts and eviction, simultaneous mutation, a disconnected client replay, Unicode edge cases, stale element references, visual timeout, content-type and size limits, file capacity, session expiry, and lease loss. Hosted concurrency evidence is a bounded read burst across independent jobs. Host OOM, sustained edge saturation, controlled WAN faults, and runner process loss across all targets remain outside that proof.
