# Hosted development-phase verification

Start with the [consumer setup and agent connection guide](../README.md). Each section below links the workflow run and the observations captured outside the runner. The five-platform, one-hour baseline is pinned to action `b57a9501805d6b75f94c6fa7ac1df4e37726a959`. The [independent consumer report](consumer-acceptance/) records the transport release and the separate Named correction, with their own immutable pins and runs.

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
| Failure investigation | The workflow and its reduced prefix each reproduced the same failed assertion after an actual application exit with code 17. The bundle retained the visible change and the native exit while excluding unapproved log fields. | [Hosted run](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44760440526) · [Evidence](failure-investigation/) |
| MCP, SDKs, and CLI | The official MCP client and TypeScript client each produced a verified UI change. An MCP-coordinated scenario and the CLI read the expected clipboard values in the live Windows and Linux apps. | [Supported tools and hosted verification](../docs/clients.md) · [Evidence](sdk/) |
| Browser inspector | Chromium controlled two live devices, mapped a real pointer click to the app, inspected native elements and a GIF, ran passing and failing workflows, and reopened the retained history. | [Hosted workflow links and reproduction](../docs/dashboard.md) · [Evidence](dashboard/) |

## Compatibility limits

| Area | Scope of the hosted evidence |
| --- | --- |
| Mobile discovery and communication | Actual Android and iOS app mDNS/Bonjour, authenticated P2pKit sessions, messaging and file consent on the isolated routed runner pair. The relay handles the pair's permitted IPv4 LAN traffic. Physical Wi-Fi, AWDL, Bluetooth, IPv6 discovery, and independent SDK peers require separate acceptance. |
| Autonomous exploration and replay | Existing-agent decisions and assertions in GTK and Windows, plus real Arabic GTK recording and replay. Provider-specific planners and broader native app coverage are separate tests. |
| Coordination | Real P2pKit Android–iOS and a live Linux–Windows group. Three-way execution has local regression coverage. Hosted three-or-more-device application workflows remain open. |
| Performance | Five-platform startup, UI transition, and process resources, plus observed desktop exit codes and Android Java crash and ANR classification. iOS crash classification and physical energy counters remain open. |
| Network and environment | Real latency, loss, link outage and recovery for the two mobile peers. Android Camera and iOS Microphone have app-level verification. Rate control has queue-timing regression coverage. Operating-system-wide network switching and physical radio conditions are outside this test link. |
| Investigation | Partial or complete failure bundles from the app, driver, screenshot and configured event sources. Host-wide or device-wide crashes may leave only the client report. The issue draft is reviewed and filed through the user's GitHub access. |
| SDKs and inspector | The official 2025-11-25 MCP client, Python, TypeScript on Node 24, and Chrome with hosted Windows and Linux. App images and video remain local. Independent MCP host and browser variants require their own acceptance. |

## Additional acceptance dependencies

| Item | Input or remaining verification |
| --- | --- |
| Named Tunnel and service-to-service Cloudflare Access | The configured publisher hostname passed an external hosted lifecycle test at `aa993a101396b7cfa1aab0891ad37a46a94153af`. See the [Named acceptance report](consumer-acceptance/#cloudflare-named-tunnel) for expiry, cancellation, and the independent installation scope. |
| Cloudflare Access in an interactive browser | An Access user policy and approved identity provider are needed to test human sign-in on the embedded browser. Service Auth and the standalone browser inspector have separate hosted results. |
| Arabic hardware keyboard | Physical composition and precise bidirectional caret and selection checks require an interactive device or workstation with an Arabic-layout hardware keyboard. Hosted text entry, clipboard, saving and app layout checks can run independently. |
| iOS native backend compatibility | The prebuilt WebDriverAgent setup is verified on the recorded `macos-26` configuration. The older `macos-15` setup requires a compatible Xcode, simulator runtime and WebDriverAgent build after its session-creation timeout. AXe passed an isolated P2pKit SwiftUI test after an app-tree and framebuffer readiness check. The paired LAN workflow has separate visible-driver evidence. |

[External acceptance procedures](../docs/external-acceptance.md) · [Connection settings and tested iOS configurations](../docs/automation.md) · [P2pKit adapter behavior](../docs/mobile-lan.md)
