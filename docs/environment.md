# Test network and app environment changes

Use these commands in an authenticated session. Add observable checks on the affected application before, during, and after each change. [Agent client](automation.md) · [Workflow assertions](record-replay.md)

## Isolated mobile LAN profiles

Dispatch the [hosted mobile LAN workflow](../.github/workflows/mobile-lan-transport.yml) in **network** mode with the two pinned P2pKit artifacts and two token digests. Set up the apps and external agent as in the [mobile LAN guide](mobile-lan.md). The Android connection owns the job-local control socket and applies the profile to both directions of the private peer link. Both mobile UI sessions and the inner authenticated relay stay available during a simulated outage.

```bash
printf '%s\n' '{"delay_ms":500,"jitter_ms":25,"rate_kbit":512,"seconds":40}' > slow.json
python3 agent.py android.connection.json --token-file "$TOKEN_FILE" \
  action network.profile.set --params-file slow.json
python3 agent.py android.connection.json --token-file "$TOKEN_FILE" action network.profile.get
python3 agent.py android.connection.json --token-file "$TOKEN_FILE" action network.profile.reset
```

Each set replaces the full link profile. `delay_ms` and `jitter_ms` are one-way values. `loss_percent` samples an independent drop decision for each eligible frame. Supply `seed` to repeat the random sequence given the same frame ordering. `rate_kbit` limits each direction separately. `offline: true` drops eligible packets in both directions. Commands return a generation, remaining lease, and controller UTC time in milliseconds. The lease defaults to 30 seconds and is bounded to 180 seconds. Reset and lease expiry restore the baseline and discard obsolete queued frames. Each direction buffers up to 128 frames. The workflow records drops and native ICMP outcomes separately from application-level assertions.

To reuse the link with another mobile app, follow the isolated LAN setup in the paired workflow and replace the app build and launch steps. The optional `network-control-socket` action input must point to the trusted controller socket under a private runner-owned directory in `RUNNER_TEMP`. The action queries the controller before publishing the session and attempts a reset when the UI connection closes. The controller accepts only the bounded profile commands. It shapes the scoped Android–iOS Ethernet frames forwarded by the bridge. Packet delivery to other networks, global Wi-Fi and cellular state, and processes outside the bridge are outside this control.

Use the coordinated P2pKit verifier with `--network-faults` to assert message delivery under delay, an observable peer disconnect during the outage, and fresh payload delivery after the link lease expires and the apps re-pair. Use [network-evidence.py](../verification/mobile-lan/network-evidence.py) with the verifier's `network.json` and the Android job artifact's `delivery.txt` and `traffic.json` to compare those app outcomes against native probes.

In hosted run 44754962439, the external agent observed `iPhone → SLOW` in Android under 500 ms configured one-way delay. Eight successful delayed ICMP probes ranged from 1,029 to 1,375 ms round trip. The 25% per-frame profile produced both delivered and lost pings. During the repeated full outage, six sampled pings had no reply, Android disabled broadcast with **No peers connected**, and both authenticated UI connections remained available. After automatic restoration, the apps re-paired through the Bonjour peer list and iOS displayed the fresh Android payload `MANGO`. Post-recovery RTT returned to 60.2–144 ms. The relay counted 119 intentional drops across the test. A profile change attempted with the other session's bearer returned HTTP 401 and both jobs completed cleanup. The original proof estimates a nine-second offset between the client and runner clocks. The current controller returns its own timestamp for future correlation. [Hosted run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44754962439) · [Screens, native probes and controller evidence](../verification/environment/network-44754962439/)

A repeat at action `2ef8755b2707f82c048eb6d53cc0426349e60350` used timestamps from the same runner clock as the native probe. Observed delayed RTT ranged from 1,027 to 1,116 ms, and all six outage probes lost their reply. The apps re-paired, iOS displayed `Android-4487 -> REOPEN`, and both jobs completed cleanup. The external verifier resumed from the observed connected pair after an early scroll targeted the wrong Android viewport. [Repeat run 44761783640](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44761783640) · [Repeat probes and app screens](../verification/environment/network-44761783640/)

## App locale and permissions

Enable the setting on an approved, disposable emulator or Simulator in your workflow.

```yaml
with:
  app-ids: dev.uitest.fixture
  app-environment: '{"dev.uitest.fixture":["camera"]}'
```

An empty permission array enables locale testing for the named app. Discover app and permission names with `app.environment.capabilities`. Commands accept only app IDs and permission names approved in the workflow. For Android use the emulator's active app locale on API 33 or later, and for iOS use app launch arguments. The iOS locale command restarts the app and subsequent launches through the action keep the selected locale. An empty locale string restores platform defaults. Use simulated OS rotation with `device.orientation` on Android and `device.rotate` on the visible Simulator. Assert your app's actual language, layout direction, and response to rotated bounds after each change. [Android per-app locales](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-16.0.0_r4/services/core/java/com/android/server/locales/LocaleManagerShellCommand.java) · [Apple localization launch arguments](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPInternational/TestingYourInternationalApp/TestingYourInternationalApp.html)

| Command | Example parameters |
| --- | --- |
| `app.locale.set` | `{"id":"dev.uitest.fixture","locale":"ar-SA"}` |
| `app.permission.set` | `{"id":"dev.uitest.fixture","permission":"camera","state":"denied"}` |

Android permission changes use `pm grant` and `pm revoke` for the configured names and report the resulting app state for user 0. Revoking a permission can stop the app. The action attempts to restore each touched Android locale and permission when the session closes. iOS uses `simctl privacy`; supported permission states include `reset`, which restores the touched authorization to its first-request state. iOS permission testing is intended for a freshly booted, disposable Simulator. Apple documents that iOS Simulator does not support Local Network privacy authorization. [Apple local-network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy)

For the hosted fixture, dispatch [Verify mobile UI session](../.github/workflows/mobile.yml) in **environment** mode. Use [mobile-environment.py](../verification/mobile-environment.py) with the downloaded connection and private token. The visible iOS path takes `--ocr /path/to/tesseract` and uses Pillow to crop the app. If the Simulator asks **Open in “Live UI fixture”?**, confirm **Open** in that Simulator and run the verifier again with a new evidence directory. Inspect screenshots and the visible labels in `observations.json`.

| Target | Hosted evidence |
| --- | --- |
| Android API 35 | The app showed English LTR, Arabic `ar-SA` RTL, granted and denied Camera permission, and landscape. It returned to English portrait. GitHub independently verified the original locale and denied Camera state after the session. [Run 44758138170](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44758138170) · [Six screenshots and platform diagnostics](../verification/environment/android-44758138170/) |
| ARM64 iOS 26.5 | The app showed `ar-SA` and RTL, rotated to landscape, and returned to portrait and English LTR. A subsequent app-level test showed Microphone granted, denied, and reset. The native policy store showed Photos grant, revoke, and reset, while the app's Photos read API still showed `undetermined` after a grant and relaunch. [Locale and rotation run 44757352949](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44757352949) · [Microphone and Photos probe 44759632099](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44759632099) · [Screens and native records](../verification/environment/ios-44757352949/) · [Microphone screenshots](../verification/environment/ios-44759632099/) |

The Android environment run used action `77fffa0eac959dc008d36f59d194c23cb3b0432b`. The iOS locale and rotation run used `c788f818ee688f49385fb9885350158da8127d07`. The first hosted link-fault run used `80a03115084c6cf25fd9eb71d05af93852ebedd3`. Rate limiting has queue-timing regression coverage. The hosted P2pKit evidence measures latency, drops, outage, and app reconnection.
