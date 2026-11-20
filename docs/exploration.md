# Agent-led UI exploration

Run `explore.py` on the existing agent's machine after a GitHub job publishes its authenticated connection. Give it a test objective and a planner command. The planner receives the current screenshot path, available command schemas, visible accessibility nodes where supported, and the last step's outcome. It selects the next action and predicts an observable postcondition. The runner checks the initial state, executes the action through the existing UI API, and waits for the predicted state.

The planner is a trusted local program or an adapter for the agent you already use. It reads one JSON object on standard input and returns one JSON proposal on standard output. The action bearer and Cloudflare Access files stay in the HTTPS client. If your planner tool requires an environment variable, opt in with `--planner-env VARIABLE`. The included file adapter lets an existing interactive agent read requests and return proposals without an extra service. [File adapter](../examples/explore_decisions.py)

```bash
mkdir -m 700 exploration-inbox
printf '%s\n' '["python3","examples/explore_decisions.py","exploration-inbox"]' > planner.json
python3 explore.py connection.json --token-file "$TOKEN_FILE" \
  --planner-command planner.json --planner-timeout 155 --steps 8 \
  --objective 'Change the sample document and verify the saved result.' \
  --output exploration-evidence
```

Use a fresh inbox and output directory per run. Give the agent the objective and access to the inbox. For each `request-N.json`, the planner should inspect the current screenshot or tree, then place a complete proposal in `decision-N.json`. Write to a temporary file before renaming it. A model adapter can implement the same standard-input and standard-output contract directly.

Add `--app-id` to launch an app already allowlisted by the runner. Keep the focused application visible and provide a bounded objective with the data and business rules the planner should test.

## Proposals

Use a unique selector for a semantic click. The runner requests a fresh snapshot and uses the same element actionability checks as the existing client. A direct action uses one of the advertised pointer, keyboard, text or device commands. Every action needs a deterministic expectation. An optional `before` assertion lets a planner prove a specific initial state even where the platform exposes a truncated tree.

```json
{
  "summary": "Replace the current draft with the supplied test text",
  "before": {"element": {"selector": {"role": "text", "text": "Old draft", "visible": true}, "state": "present"}},
  "action": {"command": "text.insert", "params": {"text": "New draft", "replace": true}},
  "expect": {
    "element": {"selector": {"role": "text", "text": "New draft", "visible": true}, "state": "present"},
    "timeout_ms": 4000
  }
}
```

For screen-only drivers, an expectation can specify `"pixel": {"x": 120, "y": 200, "rgb": [20, 190, 60], "tolerance": 3}`. Use a stable pixel with a known expected color. Pixel expectations require Pillow on the agent host. The semantic path uses the standard-library client.

To finish, return `"finish": true` with a summary and a final expectation. A run can pass after at least one verified transition. The engine checks the proposed product outcomes. Model-generated expectations still need review against the intended business rules.

## Evidence

The private output directory contains PNGs, structured observations, and `report.json`. The report records which state fingerprints were observed, which actions changed them, and which expectations passed. It reports the observed route through the application. A failed postcondition captures the current UI and rechecks the same expectation without repeating the action. An action or planner error and an unmet UI expectation have different statuses. Screenshots and app text should be reviewed before publishing them as artifacts.

The design follows the same principles as actionability checks and retried assertions in established UI test tools. Deterministic selectors, expected outcomes, and bounded waits remain part of the test even when an agent chooses the next step. [Playwright actionability](https://playwright.dev/docs/actionability) · [Playwright assertions](https://playwright.dev/docs/test-assertions) · [Playwright Test Agents](https://playwright.dev/docs/test-agents)

## Hosted verification

| Driver | Observed result |
| --- | --- |
| Linux, Mousepad 0.6.1 in an Arabic locale | An external agent read the live accessibility tree, wrote exact Arabic and English text, and verified the changed editor and saved window title. A runner-side check verified the file independently. The agent repeated a temporary edit and restored the original content. A deliberately wrong condition produced failure evidence and remained unobserved on recheck. [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44744866698) · [Screenshots and reports](../verification/exploration/mousepad/) |
| Windows, Tk fixture | The agent used the screenshot to select **Apply change**. The runner checked that the same pixel changed from `[25, 43, 66]` to `[23, 99, 59]`, and the next screenshot showed the updated label. [Run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44746015177) · [Screenshots and report](../verification/exploration/windows/) |

Both checks used structured proposals from the existing external agent. Automatic model integrations can use the same proposal contract. This verification covers the semantic and pixel paths on the listed targets. Other platform and planner combinations await their own hosted acceptance.
