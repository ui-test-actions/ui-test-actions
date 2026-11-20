# Acceptance requiring account access or physical devices

## Cloudflare Named Tunnel and Access

Use the [Named Tunnel verification workflow](../.github/workflows/named-tunnel.yml) with a dedicated remotely managed tunnel. The Cloudflare account owner must publish a hostname routed to `http://127.0.0.1:8787` and add that tunnel's connector token to this repository as the Actions secret `CLOUDFLARE_TUNNEL_TOKEN`. The runner downloads and starts the connector. The hostname should resolve to just this test tunnel during the run. The workflow serializes jobs for that hostname. [Create a Named Tunnel and route](https://developers.cloudflare.com/tunnel/get-started/)

For Access, configure a self-hosted Access application for the same hostname, with a Service Auth policy allowing a dedicated test service token. Supply that service token's client ID and secret in a private local JSON file with keys `client_id` and `client_secret`. The connector token and the Access credentials serve different purposes. [Cloudflare service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)

Dispatch with the hostname and the test UI token digest. Download the live connection artifact and run the external acceptance script. For a tunnel without an Access application, omit the Access credential argument.

```bash
python3 verification/check-named-tunnel.py connection.json \
  --token-file "$TOKEN_FILE" --access-file "$ACCESS_FILE" --output named-results
```

The script checks the runner bearer, the Access policy when configured, authenticated reconnect, a real screenshot, the final live countdown, and two terminal responses after expiry. The verification repository currently has no configured connector secret. The account-specific end-to-end check remains pending.

## Physical Arabic keyboard

Run one acceptance pass for each physical OS and native app you need to support. The person at the device needs an Arabic-layout hardware keyboard or an equivalent hardware keyboard with the active OS Arabic layout verified in Settings. Use a new document with real app input. Use the published real-app and [Unicode evidence](../verification/v2/README.md#real-applications) as the simulator and hosted desktop baseline.

1. Select the OS Arabic hardware layout. Type an Arabic word with combining marks, Arabic-Indic digits and punctuation. Switch to English with the OS shortcut and type Latin text on the same line. Add a second line and an emoji through that system's keyboard or character picker.
2. Before using a clipboard, record the app, OS version, keyboard layout, typed characters, and whether composition committed in the expected order. Capture the text field and caret on both sides of a mixed-direction boundary.
3. Use the physical arrow keys and Shift to select across the Arabic and English boundary. Record the selected substring, then replace it using the keyboard. Verify selection and caret visually, then confirm the saved Unicode text in the app.
4. Copy the result, reopen the saved document, and compare both strings against the expected Unicode code-point sequence. Exercise both RTL-leading and English-leading paragraphs. Verify multiline editing independently of the single-line case.
5. Retain the screenshots, exact code points, and visible caret and selection results for the tested apps. Use synthetic text in any shared artifact.

Hosted input, clipboard, mixed-direction preservation, and Arabic RTL layout already have automated evidence. Physical composition and hardware cursor behavior need an operator and a physical Arabic-layout device.

## Hosted iOS automation

Use the [pinned Appium workflow](../.github/workflows/native-ios.yml) for the verified `macos-26` XCUITest setup with Appium 4.0.0 and the checksum-verified ARM64 prebuilt WebDriverAgent. For AXe, use the [native accessibility workflow](../.github/workflows/ios-ax.yml) and its readiness checks. Selected host images, Xcode, runtime, and WDA versions are part of the evidence. The older `macos-15` Appium session exceeded its five-minute startup timeout. Acceptance on that image requires a compatible WDA build and a successful loopback `POST /session` before validating UI actions. [Appium capabilities and WDA setup](https://appium.github.io/appium-xcuitest-driver/latest/reference/capabilities/) · [Existing hosted iOS evidence](../verification/v2/README.md#capability-coverage)

The newer `macos-26` repeat at the baseline pin created its XCUITest session in 32.662 seconds and then timed out on its first screenshot. The adapter now switches to the native Simulator framebuffer on that timeout while retaining WebDriver's touch-coordinate validation. The AXe follow-up independently verified direct native inspection and text replacement in the real P2pKit SwiftUI sample. [Cold screenshot failure 44764871834](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44764871834) · [P2pKit SwiftUI AXe run 44765711184](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44765711184)

For Photos, the hosted Simulator still displayed its native prompt after a programmatic grant. Actual app callbacks confirmed both full access and denial when the agent selected those choices in the native UI. A repeatable programmatic pregrant that reaches the app's read-write API remains pending on this runtime. [Native permission evidence](environment.md#app-locale-and-permissions)
