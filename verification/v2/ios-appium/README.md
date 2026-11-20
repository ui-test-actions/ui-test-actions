# Hosted iOS Appium verification

The successful run loaded the published action at `b57a9501805d6b75f94c6fa7ac1df4e37726a959` on runner image `macos-26-arm64` version `20261102.0473.1`. It used Xcode 26.6, iOS Simulator 26.5, Node 24.15.0, Appium 4.0.0, XCUITest driver 13.3.0, and the arm64 iOS Simulator WebDriverAgent 17.0.12 release bundle, verified by SHA-256. Appium listened on runner loopback. The external agent used the action's authenticated connection and documented Python client. The Appium diagnostic artifact records HTTP 200 from session creation after 118.291 seconds and HTTP 200 from session deletion. [GitHub run 44700269298](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44700269298)

1. Read the XCUITest tree and activated the unique `Apply change` button using its current element reference. The tree and screenshot showed `AFTER · Button tapped`.
2. Swiped up through the list. The visible accessible rows changed from 1–12 to 10–21.
3. Sent two synchronized touch tracks. The fixture reported `Pinch expanded` in its tree and screenshot.
4. Round-tripped Arabic, Arabic-Indic numerals, English, and an emoji through the Simulator clipboard. Focused the native field, held to open its edit menu, and activated the accessible Paste item. The tree returned the exact input string and the exact applied label.

The tested adapter exposes clipboard, screenshots, semantic element targeting, and W3C gestures. Direct `text.insert` is absent from its capability response at this pin. The default visible-Simulator backend provides direct `text.insert`. The prebuilt bundle path was verified on this Apple runner and simulator combination. The earlier setup that built WebDriverAgent in the job timed out creating the session. [Earlier attempt](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44687956954) · [Pinned setup workflow](../../../.github/workflows/native-ios.yml) · [Appium prebuilt setup guide](https://appium.github.io/appium-xcuitest-driver/latest/guides/run-prebuilt-wda/)

[Semantic and gesture checks](checks.json) · [Clipboard and exact-text checks](clipboard.json) · [Capability response](capabilities.json) · [Before](initial.png) · [Button result](applied.png) · [Scroll result](swiped.png) · [Pinch result](pinched.png) · [Native Paste menu](appium-paste-menu.png) · [Unicode result](appium-unicode.png)
