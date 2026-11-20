# Android Markor verification

The external client used the Android job's connection artifact and private token file. Run 44683446672 hosted Markor v2026.10.0, pinned to source commit 04e8b92ab51ef950df5dc6efb4e21d2f1d43280c. The runner staged a synthetic text document in Documents/ui-test-actions.

1. Find the Markor storage dialog's OK control. Open the actual Android All files access screen, enable the Markor toggle through the UI, assert its checked state, and return using Android Back.
2. Dismiss the platform fullscreen notice, finish Markor onboarding, and dismiss its release notes.
3. In Markor Files, go up to Documents and open ui-test-actions/document.txt. Find the seeded text in the editing control.
4. Round-trip the Unicode test string through the device clipboard. Insert it into the focused editor with replacement and use an exact accessibility-tree assertion for the entire string. The string includes Arabic, English, Arabic-Indic numerals and punctuation, emoji, accents and line breaks. Use a regional pixel-change assertion and activate Markor's Save control.
5. Put an unrelated sentinel on the clipboard. Use Ctrl+A and Ctrl+C to copy the full editor value, and assert exact clipboard equality. Put a second native text sample on the clipboard and use Ctrl+V to replace the current selection. Assert the editor value, restore the expected text, and save it again. Capture and decode a recording during this sequence. Retry HTTP 429 session_busy within a fixed timeout using the same request ID.
6. Rotate to landscape and back to portrait. Verify actual PNG dimensions and confirm the old visual baseline is rejected after the dimension change.
7. Open View Mode and inspect the rendered text. Use Back to navigate to the file listing, long-press the file to activate Markor's file-selection controls, and reopen the document. Confirm exact editor content after reopening.
8. Replay one View Mode mutation with the same request ID. Check identical response and confirm a fresh request using the old snapshot is rejected. Check unauthenticated access, invalid coordinates, and unavailable touch hover.
9. Double-tap the word Hello and copy it with the keyboard to prove word selection. Temporarily type enough synthetic lines for scrolling, assert a visual change after scrolling, then restore and save the expected proof string.

The Markor native editing control exposes its text to Android's accessibility tree. Its rendered View Mode was verified visually because that WebView did not expose the document text in the observed tree.
