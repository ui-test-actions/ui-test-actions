# v2 hosted verification

The external clients used the repository-qualified action and the same authenticated connection artifact a consumer job receives. Each real app wrote its own data. A later GitHub job step independently checked the saved text or the simulator app's note vault. Tests used synthetic documents containing Arabic, Arabic-Indic numerals, Arabic punctuation, English, accented Latin, emoji, and line breaks. The four desktop and Android document checks allow a UTF-8 BOM, conventional platform line endings, and one trailing newline. The iOS assertion matched the exact Unicode title and body in one active, non-sample note.

## Real applications

| Target | App | Checked outcome | GitHub run and evidence |
| --- | --- | --- | --- |
| Windows | Notepad++, Win32 and Scintilla | UI Automation found the editor. Clipboard, text replacement, and Ctrl+S preserved the exact text. | [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44683919225) · [Evidence](windows/) |
| macOS | CotEditor, AppKit and SwiftUI | AX found the editor and returned the text. Native window resize and focus changed actual bounds. Paste, copy, and save preserved the exact text. | [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44684822788) · [Evidence](macos/) · [Earlier native dialog run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44683446564) |
| Linux | Notepad Next, Qt and Scintilla | Clipboard, replacement, native file selection, context menu, resize, and save. Exact text passed persistence and copy-back. | [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685999727) · [Evidence](linux/) |
| Android | Markor, AndroidX native editor and WebView | Granted storage through the visible permission UI, edited with the native test IME, saved and reopened the document, inspected both editor and preview, and verified exact text. | [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44683446672) · [Evidence](android/) |
| iOS | Thought Meadow, SwiftUI | Entered Arabic and mixed Unicode into a real note, switched to Markdown preview, and filtered the saved note with an Arabic query. | [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44683446537) · [Evidence](ios/) |

[Exact upstream commits, releases, hashes, and licenses](../real-apps/apps.json) · [Reproduction instructions](../real-apps/README.md)

Notepad Next returned an empty AT-SPI observation in the hosted Qt AppImage. It preserved the full file and clipboard content but displayed only one of the three lines correctly in the captured editing view. The Scintilla views do not establish that all Arabic text renders correctly in every app. The Thought Meadow screenshots show Arabic editing, preview, and search results. Physical Arabic keyboard layout and candidate-composition behavior require separate application tests.

## Tool and lifecycle checks

| Check | Hosted runs and evidence |
| --- | --- |
| Desktop file staging and download, byte equality, duplicate filename and traversal rejection, batch replay, visual change, GIF capture, and 24 parallel reads per runner | [Linux](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685158477) · [Windows](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685164353) · [macOS](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685170390) · [Evidence](desktop-contract/) |
| Real desktop process exit code 17, visual disappearance, relaunch, and allowlist enforcement | [Linux](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44686096299) · [Windows](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44686102819) · [macOS](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44686109493) · [Evidence](process-recovery/) |
| Test app close, launch, restart, reset, uninstall, reinstall, and rejection of unrelated app IDs | [Android](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685177176) · [iOS](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44685183256) · [Evidence](mobile-lifecycle/) |
| Android rotation, native selection and clipboard shortcuts, semantic wait and stale-ref rejection, native notification shade, recording, reconnect, and authentication | [Markor run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44683446672) · [Evidence](android/) |
| External agent using the documented Python client and browser using the Unicode controller | [iOS agent run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44683446537) · [Linux browser evidence](desktop-contract/linux/browser-arabic.png) |

The Windows recovery run was intentionally cancelled after its process checks. An independent Linux session's token and a missing bearer each returned HTTP 401 on Windows. The Windows session's own token returned HTTP 200 before cancellation and HTTP 530 about eight seconds after the cancellation request. Normal expiry was checked on separate successful workflow runs. [Cancellation trace](process-recovery/windows/cancellation.json)

App screenshots may be cropped to the display or window containing the test. Connection artifacts and raw bearer values are excluded from this directory.
