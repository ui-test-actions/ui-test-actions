# Real-application journeys

[Verify real application journeys](../../.github/workflows/real-apps.yml) downloads upstream release binaries or builds the iOS Simulator app from pinned source. [Application pins](apps.json) record each revision, binary SHA-256 digest, source license, and framework. The workflow keeps third-party app binaries on the runner.

| Target | Application | Journey and assertion |
| --- | --- | --- |
| Windows | Notepad++ | Round-trip the clipboard, edit a plain-text document in the Win32 editor, and use Ctrl+S. CI compares the saved UTF-8 file. |
| Linux | Notepad Next | Round-trip the clipboard, edit the document in the Qt AppImage on Xvfb and Openbox, and use Ctrl+S. CI compares the saved UTF-8 file. |
| macOS | CotEditor | Round-trip the clipboard, edit in the AppKit editor, and use Command+S. CI compares the saved UTF-8 file. |
| Android | Markor | Open the seeded document through Markor's Android intent, handle any native storage dialog, edit, and save. CI pulls and compares its saved UTF-8 text. |
| iOS | Thought Meadow | Create and save a local mixed-language note in the SwiftUI notebook. CI checks the stored note title, body, and active status. |

The replacement contains Arabic, English, Arabic-Indic digits, punctuation, a combining mark, emoji, and three lines. The persistence check compares the exact Unicode code points. The document assertion accepts a final newline, a UTF-8 byte-order mark, and Windows line endings.

## Run a journey from an external agent

1. Dispatch **Verify real application journeys** with the target and the SHA-256 digest of a fresh session token. Keep the original token in a private local file.
2. Download the live connection artifact and find `connection.json`.
3. Capture an initial image and inspect it for the editor and any permission or onboarding dialogs.

```bash
CONNECTION=./connection.json
TOKEN_FILE=/path/to/private-token
driver=(python3 verification/real-apps/drive.py "$CONNECTION" --token-file "$TOKEN_FILE")
"${driver[@]}" capabilities
"${driver[@]}" screenshot evidence/initial.png
```

Use the coordinates from the current screenshot. On Android, handle any system prompts and navigate back into the seeded document before using the save button coordinates. On iOS, open a blank local note before using the title and body coordinates.

```bash
# Desktop example
"${driver[@]}" edit-document --editor 200 145 --evidence evidence/desktop

# Android example
"${driver[@]}" edit-document --editor 150 190 --save 280 50 --evidence evidence/android

# iOS example
"${driver[@]}" write-note --title 500 210 --body 500 290 --evidence evidence/ios

# Work through a dialog using the current screenshot
"${driver[@]}" action pointer.click '{"x":400,"y":250}'
```

At session expiry, CI runs the storage assertion and uploads the `real-app-…` artifact. Keep the external screenshots alongside that artifact so a reviewer can compare the UI change with the saved state.
