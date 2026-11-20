# Investigate a failed UI test

Capture evidence while the authenticated runner session is still live. Give the workflow client a new private output directory.

```bash
python3 workflow.py run journey.yaml connection.json --token-file "$TOKEN_FILE" \
  --output replay --screenshots --diagnostics --diagnostic-app-id timed-fixture
```

When the test diverges, `replay/diagnostics/manifest.json` records the failing stage, available files, capture timestamps, and SHA-256 digests. It also records unavailable captures with structured statuses. An unavailable runner can still produce a manifest with the failed step and HTTP status. The workflow exits in failure even when evidence collection succeeds.

The collector uses the enabled capabilities of the existing session. It records the failure screenshot, structural accessibility tree, startup and command timings, an allowed app process, and an active isolated link profile when each is available. It omits tree text and labels by default. Screenshots and recordings can contain the visible application data. Keep the generated report and images on the private client until they have been reviewed for sharing.

Add `--diagnostic-recording-seconds 6` to collect an optional short clip after the failure. To retain application behavior leading up to the failure, use the recorded workflow steps and the per-step screenshots. For an interactive session, run the collector directly with `python3 diagnose.py capture connection.json --token-file "$TOKEN_FILE" --output evidence`. Its `--include-tree-content` option includes labels and text in the local bundle.

## Include application and system diagnostics

Write structured JSON Lines from the application or its test harness and opt in to the exact event names the agent needs.

```yaml
with:
  diagnostic-logs: >-
    {"app":{"path":"ui-app-events.jsonl","events":["ui.ready","process.failed"]}}
```

Set the application or harness to write the file under `RUNNER_TEMP`. An event such as `{"event":"process.failed","epoch_ms":1795188400000,"level":"error","code":17}` supplies a timestamp and exit code. The action returns the approved event name and supported metadata. Free-form messages and unknown fields stay in the job. The reader bounds the tail to 64 KiB and returns at most 80 approved events per source. Configure another named source to include system or device events after filtering them through your own workflow. The action does not retrieve host or device logs globally.

## Reproduce on a clean app state

Generate a smaller workflow that preserves the instructions through the first failing step. The prefix expands reusable blocks and retains the workflow's original input names.

```bash
python3 diagnose.py prefix journey.yaml replay/report.json reduced.json
python3 workflow.py run reduced.json fresh-connection.json --token-file "$FRESH_TOKEN_FILE" \
  --output repeat --diagnostics --diagnostic-app-id timed-fixture
python3 diagnose.py issue-draft repeat/diagnostics/manifest.json issue.md
```

Use a freshly provisioned app or a workflow reset that is safe for the fixture. Compare the two reports and the independent app or operating-system evidence before attributing a cause. The issue draft contains the target, failed stage, operation, error code, and a stable signature. Review the draft and add sanitized evidence links. To file it through GitHub, run `gh issue create --title "UI regression" --body-file issue.md`. To replace a known issue's body, use `gh issue edit ISSUE_NUMBER --body-file issue.md`.

[Playwright trace diagnostics](https://playwright.dev/docs/trace-viewer) · [XCTest screenshot attachments](https://developer.apple.com/documentation/xctest/xctattachment)
