# Five-platform session lifetime and cancellation evidence

The consumer workflows use `ui-test-actions/ui-test-actions@b57a9501805d6b75f94c6fa7ac1df4e37726a959`. GitHub's job setup logs identify that exact resolved action SHA. The short consumer runs used workflow commit `63613313fb573caec4d72cace62884d51809fa39`. The first hour runs and cancellation runs used workflow commit `4c944299580ab7eb1f515abc7af077a62dba3f3c`. The iOS hour and cancellation reruns used workflow commit `0b50eb7e586a23dc02dced1f3796e14bd5167507` with the `macos-26` image. The desktop and mobile proof workflow definitions were identical at all three commits.

[Setup and external client](../../../README.md#add-the-action-to-a-workflow) · [Full verification report](../README.md) · [Desktop proof workflow](../../../.github/workflows/desktop.yml) · [Mobile proof workflow](../../../.github/workflows/mobile.yml)

## Hosted runs and observations

All timestamps in the table use UTC on the external verification host. The elapsed duration comes from the runner log.

| Target | Consumer run | Real-app run and evidence | 60-minute run | First authenticated HTTP 200 | Runner elapsed | UI change before expiry | Last HTTP 200 | First terminal response |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [Windows](windows/) | [44693002473](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44693002473) | [44694463531](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44694463531) · [LocalSend](../flutter-windows/) | [44699140340](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699140340) | 08:03:33.279 | 3600.339 s | 50 s left | 09:01:08.278 · 2 s left | HTTP 530 at 09:01:10.873, then HTTP 530 at 09:01:33.944 |
| [macOS](macos/) | [44693002132](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44693002132) | [44700501147](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44700501147) · [CotEditor](../real-app-exact/macos/) | [44699140729](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699140729) | 08:03:33.149 | 3600.723 s | 50 s left | 09:01:18.426 · 0 s left | HTTP 530 at 09:01:20.959, then HTTP 530 at 09:01:42.291 |
| [Linux](linux/) | [44693002136](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44693002136) | [44697310688](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44697310688) · [LocalSend](../flutter-linux/) | [44699140778](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699140778) | 08:03:33.189 | 3600.765 s | 50 s left | 09:00:53.129 · 0 s left | HTTP 530 at 09:00:55.669, then HTTP 530 at 09:01:18.290 |
| [Android emulator](android/) | [44693001890](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44693001890) | [44700501182](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44700501182) · [Markor](../real-app-exact/android/) | [44699140338](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699140338) | 08:03:33.142 | 3600.556 s | 51 s left | 09:02:03.195 · 2 s left | HTTP 530 at 09:02:05.806, then HTTP 530 at 09:02:28.619 |
| [iOS Simulator](ios/) | [44693002066](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44693002066) | [44700501405](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44700501405) · [Thought Meadow](../real-app-exact/ios/) | [44706945964](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44706945964) | 09:07:18.251 | 3600.639 s | 45 s left | 10:07:05.401 · 2 s left | HTTP 530 at 10:07:08.065, then HTTP 530 at 10:07:30.951 |

| Target | Cancellation run | Last HTTP 200 after submission | First terminal response after submission | Evidence |
| --- | --- | --- | --- | --- |
| Windows | [44699297625](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699297625) | 9.601 s | HTTP 530 at 11.060 s | [Trace](windows/cancellation.json) |
| macOS | [44699297711](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699297711) | 16.645 s | HTTP 530 at 19.382 s | [Trace](macos/cancellation.json) |
| Linux | [44699297712](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699297712) | 13.835 s | HTTP 530 at 15.309 s | [Trace](linux/cancellation.json) |
| Android emulator | [44699297271](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699297271) | 13.852 s | HTTP 530 at 18.446 s | [Trace](android/cancellation.json) |
| iOS Simulator | [44711587913](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44711587913) | 23.715 s | HTTP 530 at 26.733 s | [Trace](ios/cancellation.json) |

## How the evidence was collected

- The external verification host generated a separate bearer for each job, dispatched the workflow with its SHA-256 digest, downloaded the session artifact, and used the documented Python agent client over HTTPS. The runner hosted the application and tunnel. The external client inspected the screenshot, changed fixture state, and compared the screenshots. A fresh client identified the same session and observed the resulting UI.
- All five simultaneously live endpoints in the first set accepted their own bearer and returned HTTP 401 for anonymous requests and another live session's bearer. The iOS rerun repeated these checks using the live cancellation job's bearer. A burst of 48 reads with six concurrent clients per runner returned HTTP 200 and the same session ID on every request. Opening and late screenshots show the fixture changing from its initial state to `AFTER · Hour start` and then `AFTER · Hour end`.
- The runner timestamps measure elapsed time from the ready event to normal shutdown. External observations use a different clock. The live endpoint supplies its own authenticated countdown rounded to the nearest second. A successful read showing zero therefore still precedes expiry. The post-expiry polling offset is relative to the external observer's estimate derived from that countdown. A recorded Cloudflare HTTP 530 is a terminal edge response for this Quick Tunnel hostname, corroborated by later terminal polls and the completed workflow.
- Cancellation was measured on separate runs using the same pin and one request per target. Timing begins immediately before submitting `gh run cancel`. The table brackets when the observer saw access disappear between the last HTTP 200 and the first terminal response. GitHub independently reported `cancelled` for each run. These are observed times from this sample.
- The fixture exercises lifetime independently of third-party startup and updates. The linked real-app runs use the same published action pin and provide separate screenshots and persistence assertions for upstream applications.

Each platform directory contains the opening and authentication results, periodic and concurrent reads, late action result, expiry and cancellation traces, runner events, and early and late screenshot pairs. The machine-readable index is [matrix.json](matrix.json). The evidence excludes connection artifacts, bearer values, and full runner logs.

## First iOS attempt

GitHub showed a successful workflow and logged normal shutdown after 3,601.286 seconds on `macos-15`. The external client lost access earlier. Its last HTTP 200 had 499 seconds left, followed by HTTP 502 and repeated HTTP 530. A follow-up HTTP 530 response identified Cloudflare error 1033, which means the edge had no healthy connector to route to. The first iOS run therefore failed the external hour check. The retry uses `macos-26` and a freshly registered Quick Tunnel. The evidence establishes that the first route lost connectivity and leaves the cause of that connector loss undetermined. [First iOS run 44699141850](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699141850) · [Failure trace](ios-first-attempt.json) · [Cloudflare error documentation](https://developers.cloudflare.com/tunnel/troubleshooting/#i-see-an-error-1033-when-attempting-to-run-a-tunnel)

A separate `macos-26` cancellation attempt stopped during startup when `xcrun simctl list devices booted -j` exceeded 20 seconds. Its rerun opened, passed external UI and authentication checks, and measured cancellation on the same runner image as the hour rerun. The earlier `macos-15` cancellation also succeeded. [Simulator startup timeout](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44710804533) · [Earlier iOS cancellation](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699297963)

## Reproduce

Copy one of the workflows linked above or dispatch it from this repository. Use the documented token and connection artifact exchange. Use the external verification script for these particular fixtures. The normal client remains independent of Pillow.

```bash
python3 -m pip install Pillow==12.2.0
python3 verification/probe_lifetime.py open connection.json --token-file "$TOKEN_FILE" --evidence evidence
python3 verification/probe_lifetime.py checkpoint connection.json --token-file "$TOKEN_FILE" --evidence evidence
# Start before the final minute. This waits and emits late UI and shutdown evidence.
python3 verification/probe_lifetime.py expire connection.json --token-file "$TOKEN_FILE" --evidence evidence
# Dispatch a separate short run with a fresh token to measure cancellation.
python3 verification/probe_lifetime.py cancel cancel-connection.json --token-file "$CANCEL_TOKEN_FILE" --evidence cancellation --run-id "$RUN_ID"
```

For the visible Simulator fixture on `macos-26`, add `--ios-runner macos-26` to the probe commands. Confirm the screenshot shows the expected fixture and its startup prompt. Runner image updates can move elements.
