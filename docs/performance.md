# Measure UI performance and process resources

Use the action's measurements with an existing authenticated UI session. Provide a meaningful `ready` check in the workflow. A check for a visible, usable app state gives the readiness timing that interpretation. The runner measures when its launch command returned and when its readiness command succeeded.

```bash
python3 agent.py connection.json --token-file "$TOKEN_FILE" action performance.observations
python3 measure.py collect connection.json --token-file "$TOKEN_FILE" \
  --app-id test-app --count 8 --interval-ms 1000 --output performance.json
```

Configure `desktop-apps` and start the registered app through `app.launch` to measure its owned desktop process. Use `app-ids` on Android and iOS to restrict which app can be sampled. Omit `--app-id` to collect startup and driver timings alone.

| Measurement | Source |
| --- | --- |
| Launch and readiness | Runner monotonic clock around the consumer's launch command and successful readiness check. |
| Driver execution | Runner monotonic clock for the last 256 actual command executions. Names, durations, and success flags are stored. |
| Action and observed transition | The workflow report records client action time, expectation time, and elapsed time from action to a passing expected state. These include transport and observation. |
| Linux CPU and resident memory | App process ticks and resident pages from procfs. |
| macOS CPU and resident memory | App process CPU time and resident size from `ps`. |
| Windows CPU and working set | `Get-Process` cumulative CPU time and working set in bytes. Window response status is available when the process has a main window. |
| Android memory and CPU | Native `dumpsys` PSS/RSS and recent CPU when reported, plus cumulative process CPU time from `ps TIME` with whole-second resolution. If available after exit, the OS reason includes its numeric code and label. |
| iOS Simulator CPU and resident memory | The app process identified by Simulator `launchctl` and sampled on its macOS host. |

Read RSS, PSS, and Windows working-set numbers as their named metrics. Cumulative CPU samples from the same process let the collector calculate utilization as a percentage of one core using runner timestamps. The controlled desktop process reports its actual exit code. Physical battery and energy measurements require physical-device instrumentation. Hosted process state data covers the operating system's reported signals.

## Compare runs

Collect the same app and target under equivalent conditions with a consistent workflow. Compare the reported medians. Optional limit values express the maximum allowed absolute increase in the metric's own units. Choose limits from the application's performance budget and runner variability.

```bash
printf '%s\n' '{"driver.pointer.click.milliseconds":150}' > limits.json
python3 measure.py compare baseline.json candidate.json --limits limits.json --output comparison.json
```

The comparison exits with status 1 when a configured limit fails. Metric names include the measurement source where applicable. An unavailable metric is omitted from the report, and a limit for one produces an explicit error. [Windows process metrics](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/get-process) · [Android system diagnostics](https://developer.android.com/tools/dumpsys)

## Hosted verification

The external client clicked **Apply** and asserted the fixture's blue-to-green transition from before-and-after screenshots. The reports include startup, transition, and process samples. The desktop fixture also exited with code 17 on all three desktops. Linux was sampled again after a fresh launch and passed a configured comparison limit.

| Platform | Consumer workflow | Evidence |
| --- | --- | --- |
| Linux | [44751965086](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44751965086) | [Startup, transition, process and comparison](../verification/performance/linux/) |
| Windows | [44751973840](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44751973840) | [Startup, transition and process](../verification/performance/windows/) |
| macOS | [44751981817](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44751981817) | [Startup, transition and process](../verification/performance/macos/) |
| Android emulator | [44752856211](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44752856211) | [Startup, transition and process](../verification/performance/android/) |
| ARM64 iOS Simulator | [44752006370](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44752006370) | [Startup, transition and process](../verification/performance/ios/) |

The desktop and iOS runs used action `ca3d59b9a5ae10832ae00320bace38e4f65e3367`. The Android run used `4d80e9ccb8dbfafc789cb17011f38572c825d816`. Android reported zero whole CPU seconds for the light fixture between samples. Mobile crash and ANR classification still needs a deliberately faulting hosted app test. Physical battery and energy counters need physical-device instrumentation.
