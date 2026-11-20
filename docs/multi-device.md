# Coordinate multiple live devices

Use `coordinate.py` from the existing agent's machine to drive two to eight live UI sessions. Each device has its own connection artifact and private bearer. The coordinator checks that every name resolves to a different session. The runner jobs can mix platforms when the [workflow commands](record-replay.md) are compatible.

Store a private device map with paths relative to that file.

```json
{
  "android": {"connection": "android.connection.json", "token_file": "android.token"},
  "ios": {"connection": "ios.connection.json", "token_file": "ios.token"}
}
```

```bash
python3 coordinate.py scenario.json --devices devices.json \
  --inputs fixtures.json --output coordinated-evidence
```

A scenario has `version: 1`, an optional list of declared `inputs`, and ordered `stages`. Each stage maps device names to versioned workflows, read-only captures, or both. The coordinator validates every device's operations for the stage before sending a mutation. Devices in a stage run in parallel. A later stage starts after all devices in the previous stage pass.

Captures bind values for later stages. Use `clipboard_text`, `element_text` with a unique visible selector, or `file_sha256` with a plain filename in a runner's configured exchange directory. An `equal` pair compares two available values. Reports list binding names and comparison outcomes. Capture variables can feed workflow inputs using `{"input":"name"}`.

```json
{
  "version": 1,
  "stages": [
    {
      "name": "Read the source clipboard",
      "devices": {"android": {"capture": {"test_value": {"kind": "clipboard_text"}}}}
    },
    {
      "name": "Write and verify the value on iOS",
      "devices": {
        "ios": {
          "workflow": {
            "version": 1,
            "inputs": ["test_value"],
            "steps": [
              {"action": {"command": "clipboard.set", "params": {"text": {"input": "test_value"}}}}
            ]
          },
          "capture": {"received_value": {"kind": "clipboard_text"}}
        }
      },
      "equal": [["test_value", "received_value"]]
    }
  ]
}
```

This example copies a test value through the coordinator. For a peer-to-peer test, perform the send in the source application and observe the result in the receiver application. The [hosted mobile LAN](mobile-lan.md) supplies a real network path for Android and iOS P2pKit samples. Use a device capture or a file digest assertion to check the result independently of the sender.

When a stage fails, earlier mutations remain applied and later stages are skipped. Use `before` assertions to establish the intended starting state before replaying a failed stage. The clients can reconnect to the same live sessions using the published connection settings. If a job ends, dispatch a new job and supply its new connection artifact. The optional scenario `cleanup` map runs explicitly supplied per-device workflows, even after an assertion failure. GitHub job expiry and cancellation own runner and tunnel teardown.

## Hosted verification

The coordinator used a fresh Android emulator and Apple Silicon iOS Simulator pair at the [mobile LAN action pin](mobile-lan.md). The apps discovered and authenticated one another. The coordinator verified separate clipboard values and then carried an Android observation across a completed stage for iOS to consume.

The live iOS app offered its 200 KiB fixture over P2pKit. The Android phase waited for the incoming consent prompt, accepted the file, observed completion at 100%, and checked the receiver's displayed SHA-256 against the deterministic fixture digest. The iOS app showed the completed send. A new coordinator client reconnected to both live endpoints and rechecked the Android digest and the iOS progress bar. [Paired run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44748786296) · [Scenario and stage report](../verification/multi-device/) · [Android result](../verification/multi-device/android-completed.png) · [iOS result](../verification/multi-device/ios-sender-result.png) · [Reconnect report](../verification/multi-device/reconnect/report.json)

The hosted transfer evidence covers the Android–iOS combination. Unit tests exercise three concurrent sessions, shared bindings, preflight rejection, cross-device assertion failure, and configured cleanup. Additional platform combinations and network topologies require their own acceptance checks.
