# Hosted development-phase verification

Start with the [consumer setup and agent connection guide](../README.md). Each section below links the workflow run and the observations captured outside the runner. The five-platform, one-hour baseline is pinned to action `b57a9501805d6b75f94c6fa7ac1df4e37726a959`. New capabilities have separate immutable pins and acceptance runs.

## Five-platform session baseline

All five consumer workflows provided an authenticated screen, accepted a UI action from a client outside the job, and let a fresh client see the resulting state. At the same action pin, every platform completed a separate one-hour run with a visible action in the last minute and later terminal responses to authenticated requests.

| Target | Consumer run | Real application evidence | Last live at expiry boundary | First terminal after cancellation |
| --- | --- | --- | --- | --- |
| Windows | [44693002473](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44693002473) | [LocalSend](v2/flutter-windows/) | [2 seconds left](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699140340) | [11.060 seconds](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699297625) |
| macOS | [44693002132](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44693002132) | [CotEditor](v2/real-app-exact/macos/) | [0 rounded seconds left](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699140729) | [19.382 seconds](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699297711) |
| Linux | [44693002136](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44693002136) | [LocalSend](v2/flutter-linux/) | [0 rounded seconds left](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699140778) | [15.309 seconds](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699297712) |
| Android emulator | [44693001890](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44693001890) | [Markor](v2/real-app-exact/android/) | [2 seconds left](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699140338) | [18.446 seconds](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44699297271) |
| iOS Simulator | [44693002066](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44693002066) | [Thought Meadow](v2/real-app-exact/ios/) | [2 seconds left](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44706945964) | [26.733 seconds](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44711587913) |

The source report records opening, last live and first terminal UTC times for each target, plus the runner's elapsed time and each cancellation bracket. The iOS `macos-15` hour attempt lost its Quick Tunnel before the deadline. The `macos-26` rerun passed the external hour check. [Lifetime and cancellation evidence](v2/lifetime/) · [v2 platform and command coverage](v2/README.md)

## Development-phase acceptance

| Capability | Observed result | Runs and evidence |
| --- | --- | --- |
| Hosted mobile LAN | Concurrent Linux KVM Android and Apple Silicon iOS. Original mDNS/Bonjour frames reached both peers. Both native P2pKit samples discovered each other, exchanged authenticated chat, and completed an approved file transfer with an exact SHA-256. A repeat exercised rejection and Bonjour withdrawal and rediscovery. | [Automated chat](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44741710196) · [File transfer](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44736388856) · [Rejection and rediscovery](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44737698097) · [Evidence and app pins](../docs/mobile-lan.md) |
| Autonomous exploration | An existing external agent chose actions using the observed GTK editor and Windows fixture. Each successful action had a deterministic assertion. The GTK case saved exact mixed Arabic text and repeated a deliberately false assertion. | [Mousepad](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44744866698) · [Windows](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44746015177) · [Screenshots and reports](exploration/) |
| Record and replay | Two fresh Linux Mousepad sessions recorded and replayed semantic menu targeting, Unicode insertion and explicit assertions. The source and replay saved identical file hashes. | [Record](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44747466797) · [Replay](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44747474443) · [Reports and saved results](record-replay/) |
| Multi-device orchestration | Independent Android and iOS sessions coordinated approved app-file consent and transfer. The receiver verified the payload's exact hash and both apps logged authenticated completion. | [Paired run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44748786296) · [Stages, assertions and native reports](multi-device/) |
| Performance and process metrics | External before-and-after UI assertions and native CPU and memory fields on five hosted targets. The controlled desktop processes reported exit 17. Linux passed a repeated profile and configured comparison. | [Five hosted runs and per-platform measurements](../docs/performance.md#hosted-verification) |
| Network and mobile environment | The live P2pKit pair delivered a message under delay, lost its peer during the isolated outage, then re-paired and delivered a fresh message after automatic recovery. Android displayed granted and denied Camera states. Both mobile apps displayed Arabic RTL, rotated, and returned to their default layout. | [Network fault and recovery run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44754962439) · [Screens, native probes, app states and iOS authorization limits](../docs/environment.md) |

## Additional acceptance dependencies

| Item | Input or remaining verification |
| --- | --- |
| Named Tunnel | The verification repository has no configured connector secret. Live verification requires a dedicated Cloudflare-routed hostname mapped to `http://127.0.0.1:8787` and the matching `CLOUDFLARE_TUNNEL_TOKEN` Actions secret. |
| Cloudflare Access | Live verification on that hostname requires an Access application, Service Auth policy, and a test service token ID and secret supplied privately to the external agent. |
| Arabic hardware keyboard | Physical composition and precise bidirectional caret and selection checks require an interactive device or workstation with an Arabic-layout hardware keyboard. Hosted text entry, clipboard, saving and app layout checks can run independently. |
| iOS native backend compatibility | The prebuilt WebDriverAgent setup is verified on the recorded `macos-26` configuration. Compatibility outside that configuration needs a matching Xcode, simulator runtime and WebDriverAgent build. The older `macos-15` startup timed out and native AXe inspection of the P2pKit SwiftUI sample failed. UIKit and Thought Meadow AXe evidence and the visible P2pKit driver are separately available. |

[Connection settings and tested iOS configurations](../docs/automation.md) · [P2pKit adapter behavior](../docs/mobile-lan.md)
