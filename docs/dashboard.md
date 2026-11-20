# Inspect live sessions in a browser

Start the optional inspector on the operator's machine with the same [private session registry](clients.md) as the CLI and MCP.

```bash
python3 dashboard.py --sessions sessions.json --history ./ui-history
```

Open the private loopback link printed by the command. The inspector accepts requests only at its exact local address. It uses an ephemeral dashboard key and reads runner tokens from the local registry. No token travels in an API URL. The dashboard key stays in the browser tab's session storage. Close the local Python process when finished. The GitHub job controls the runner session's own expiry and cleanup.

| View | Use |
| --- | --- |
| Devices | Switch between live sessions and see their remaining time. |
| Live screen | Capture a frame, turn polling on, or enable direct click and drag on the displayed image. Coordinates are mapped back to the runner's actual screenshot pixels. |
| Accessibility | Refresh and filter the native tree. Click a visible element when the runner advertises semantic targeting. |
| Commands | Use the runner's advertised command schemas, including input, gestures, recording, app lifecycle, and optional diagnostic sources. A stopped session recording appears as a GIF in Results. |
| Replay workflow | Paste a versioned single-device workflow or coordinated scenario and its inputs. The results include the same assertions and step timeline as the existing replay engine. |
| Run history | Reopen a completed or failed report and view its available screenshot artifacts. The directory passed to `--history` preserves runs across restarts. |

Live preview is off at startup and pauses while the tab is hidden. The inspector runs locally and leaves headless CI and the hosted Action setup independent. One writing operation runs at a time in the dashboard. Keep the selected app and its test data safe to display before capturing or sharing screenshots, GIFs, or accessibility labels.

The browser acceptance exercise uses Playwright and an existing Chromium executable. It used two live consumer workflows, changed the Linux fixture through a browser click, inspected five Windows UI Automation nodes, captured a Windows GIF, and compared both devices' exact Arabic clipboard values. The same history survived a local server restart and browser reload. Anonymous API reads returned 401 and cross-origin mutations returned 403. [Linux runner 44763696026](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44763696026) · [Windows runner 44763704618](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44763704618) · [Verifier](../verification/dashboard-check.py) · [Browser and runner evidence](../verification/dashboard/)
