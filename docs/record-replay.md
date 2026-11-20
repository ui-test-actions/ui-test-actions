# Record and replay UI actions

Start an interaction recording on a live UI session. The runner records supported inputs sent through the browser controller and HTTP API, including keyboard, pointer, touch, text, clipboard writes, semantic clicks, lifecycle actions, and the assertion commands in use. The recording belongs to the authenticated session and is separate from its GIF screen recorder.

```bash
python3 agent.py record-connection.json --token-file "$RECORD_TOKEN" action trace.start
# Interact with the application and issue the assertions you want to keep.
python3 agent.py record-connection.json --token-file "$RECORD_TOKEN" action trace.stop > trace.json
python3 workflow.py export trace.json test.yaml
python3 workflow.py export trace.json test.py
```

Copy the recording before the session expires. The default capture replaces text parameters and exact text selectors with named input references. Supply those values in a separate JSON file for replay. Use `trace.start` with `{"capture_text":true}` when the test inputs are intended to be embedded. A trace capped at 160 events or 240,000 bytes reports truncation. A failed recorded command keeps its name and error code. Resolve either case before exporting.

Open a fresh runner with the same initial app state and replay the exported document.

```bash
python3 workflow.py run test.yaml replay-connection.json \
  --token-file "$REPLAY_TOKEN" --inputs inputs.json --output replay-evidence
# The generated Python entry point uses the same runner.
PYTHONPATH=. python3 test.py replay-connection.json \
  --token-file "$REPLAY_TOKEN" --inputs inputs.json --output python-replay-evidence
```

The YAML export uses the JSON-compatible syntax of YAML 1.2. Handwritten YAML with block indentation can be loaded with PyYAML. A successful [exploration report](exploration.md) is also an export source. Its verified preconditions and assertions stay with its actions.

## Editing a workflow

Each workflow declares `version: 1` and a list of `steps`. An `action` can use a fresh semantic `selector` or a supported `command` and `params`. Add `before` and `expect` assertions to describe specific starting and ending states. Use an `expect` by itself for a checkpoint. Reuse a group of steps by naming it under `blocks` and adding `{"use":"block_name"}` to the main list. Put input names under the workflow's `inputs` and reference them as `{"input":"name"}` in an action or assertion.

The runner validates command availability and arguments before issuing any action. It resolves semantic clicks against each current UI tree. Coordinate recordings require the original runner target and display dimensions. Place a semantic or visual checkpoint around coordinate actions that depend on layout. Use wait assertions to control asynchronous transitions. Recorded timestamps are evidence only.

The first divergent step stops replay. The report includes the step index, whether the action or assertion failed, and a screenshot when the session can still capture one. Use `--screenshots` to retain every step in addition to the initial and final captures. Keep evidence and input files with the test data they contain.

## Hosted verification

The record and replay workflows opened two fresh Mousepad sessions in the Arabic GTK locale at action pin `07a58ce720fd28c8886abe0b5f8b30ff00044c54`. The recorded path contained a semantic File-menu click, keyboard actions, one multilingual text insertion, and three assertions. Repeating the insertion request with the same ID produced one recorded action, and the trace stored parameter names in place of the typed text.

The exported YAML and Python each replayed successfully on the second session after restoring the original editor contents. The agent also replayed a workflow exported from the successful exploration report and a variant that used the same File-menu block twice. A missing-input run stopped before its first action. The example inputs contain the synthetic text used in this test. [Recording run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44747466797) · [Replay run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44747474443) · [Trace, workflows, screenshots, and reports](../verification/record-replay/)
