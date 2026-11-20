# GitHub-hosted runner verification

On November 20, 2026, the [desktop](../.github/workflows/desktop.yml) and [mobile](../.github/workflows/mobile.yml) workflows pulled `ui-test-actions/ui-test-actions@af3c8d69a98c90a15c39055be1b019d82e5ce307` using a repository-qualified `uses:` line. The external agent downloaded each live connection artifact and used the documented curl commands and a private token file from outside the jobs. It inspected the PNGs and acted on the controls in the screenshots.

| Target | GitHub Actions run | Observed change and evidence |
| --- | --- | --- |
| Linux | [44677511806](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44677511806) | Typed and clicked Apply. [Before](linux/before.png) · [After](linux/after.png) · [Browser controller](linux/browser.png) · [Checks](linux/checks.txt) |
| Windows | [44677512108](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44677512108) | Typed and clicked Apply, then cancelled the job to verify revocation. [Before](windows/before.png) · [After](windows/after.png) · [Checks](windows/checks.txt) |
| macOS | [44677511799](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44677511799) | Typed and clicked Apply. [Before](macos/before.png) · [After](macos/after.png) · [Checks](macos/checks.txt) |
| Android | [44677324128](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44677324128) | Typed, tapped Apply, and swiped from row 1 to row 6. [Before](android/before.png) · [After](android/after.png) · [Checks](android/checks.txt) |
| iOS | [44676596337](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44676596337) | Typed, tapped Apply, and swiped from row 1 to row 12 inside the visible iPhone 17 Pro Simulator window. [Before](ios/before.png) · [After](ios/after.png) · [Checks](ios/checks.txt) |

The fixture was blue at the start and turned green after Apply, with the externally entered text in its status label. Desktop and iOS screenshot pairs are cropped to the fixture or Simulator window. The Android images are the full emulator framebuffer.

For every target, missing and incorrect bearer tokens returned HTTP 401. A new HTTP connection authenticated with the original token and returned the same session ID. On Windows, the valid token's screenshot request returned Cloudflare HTTP 530 about 10 seconds after cancellation was requested. The completed run still returned 530.

The Linux browser screenshot shows a separate client authenticated to the same session after the terminal actions. The browser performed a second click, type, and click sequence and refreshed the screenshot.

The iOS fixture also passed on the `macos-15` image with iOS 26.2. Typing and Apply changed the status, and a swipe advanced the list to row 10. [Run 44677363881](https://github.com/ui-test-actions/ui-test-actions/actions/runs/44677363881) · [Before](ios/macos-15/before.png) · [After](ios/macos-15/after.png) · [Checks](ios/macos-15/checks.txt)
