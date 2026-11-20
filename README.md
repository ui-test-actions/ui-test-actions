# Live UI testing on GitHub Actions

Run your app on a GitHub-hosted runner and control its live UI over HTTPS. An existing agent can inspect the screen, discover native capabilities, act, and verify the result in the same session. The browser controller shares the runner with the API. The tunnel connector runs on the runner, and the agent can use Python's standard library or an existing HTTPS client.

## Add the action to a workflow

Start from a [desktop](examples/desktop.yml), [Android](examples/android.yml), or [iOS](examples/ios.yml) workflow and replace its build, launch, and readiness commands. The examples use the immutable v2 candidate. [Action commit](https://github.com/ui-test-actions/ui-test-actions/commit/b57a9501805d6b75f94c6fa7ac1df4e37726a959)

```yaml
- uses: ui-test-actions/ui-test-actions@b57a9501805d6b75f94c6fa7ac1df4e37726a959
  with:
    target: linux
    token-sha256: ${{ inputs.token_sha256 }}
    duration-minutes: '60'
    launch: bash ci/launch-desktop-app.sh
    ready: bash ci/check-desktop-ready.sh
```

Declare a required string `workflow_dispatch` input named `token_sha256` and set up Python 3.12 earlier in the job. The job timeout must accommodate the build, startup, and session. The action runs `launch` and `ready` in Bash, including on Windows. The scripts run in the caller's workspace. Start a long-running desktop app in the background so `launch` can exit. You can omit `launch` to attach to an already running app.

| Target | Tested runner | Application setup |
| --- | --- | --- |
| `linux` | `ubuntu-24.04` | Start the app in the action's X11 desktop. The action starts Xvfb when there is no display. |
| `windows` | `windows-2025` | Start the GUI executable in the runner's interactive desktop. |
| `macos` | `macos-15` | Start the GUI app with `open -a /path/to/App.app` or your own launch script. |
| `android` | `ubuntu-24.04` | Boot a KVM-enabled emulator, install your APK, and launch its activity. |
| `ios` | `macos-15`, `macos-26` | Boot an iOS simulator, install a simulator build of your `.app`, and launch the bundle ID. The default controller drives the visible Simulator window. |

[GitHub-hosted runner images and labels](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

| Input | Meaning |
| --- | --- |
| `target`, `token-sha256` | Required platform and lowercase SHA-256 digest of the one-time token. |
| `duration-minutes` | Whole minutes after app readiness and tunnel registration, from 1 to 180. Defaults to 15. |
| `launch`, `ready` | Optional Bash launch script and readiness check. Without `ready`, the action checks the initial screenshot. |
| `startup-timeout-seconds` | Launch and readiness budget from 1 to 1800 seconds. Defaults to 180. |
| `device` | ADB serial or Simulator UDID. Required if multiple eligible devices are available. |
| `display-size` | Size of the Linux virtual display, such as `1440x900`. Defaults to `1280x800`. |
| `desktop-apps` | JSON map of approved desktop app IDs to workflow-defined executable arguments and an optional working directory. Enables process commands. |
| `app-ids`, `app-installs`, `deeplink-schemes` | Approved mobile lifecycle IDs, package paths, and URL schemes. |
| `android-ime` | Enables the test-only Android Unicode input method by default. Set `'0'` to disable it. |
| `file-exchange` | Set `'1'` to enable bounded desktop file staging and retrieval. |
| `webdriver-url`, `webdriver-capabilities` | Optional runner-local Appium server and JSON capabilities. See backend verification status before adoption. |
| `ios-axe-path` | Optional path to a runner-installed AXe executable for native Simulator elements. The setup and tested ref are in the automation guide. |
| `tunnel-hostname`, `tunnel-token`, `origin-port` | Optional dedicated Cloudflare named tunnel. Use a GitHub secret for its connector token. |

[Automation API, platform limits, and optional inputs](docs/automation.md)

## Connect and hand the session to an agent

Generate a fresh token on the client machine for each run. Keep the raw token file private.

```bash
TOKEN_FILE=$(mktemp)
TOKEN=$(openssl rand -hex 32)
printf '%s\n' "$TOKEN" > "$TOKEN_FILE"
TOKEN_SHA256=$(printf '%s' "$TOKEN" | openssl dgst -sha256 | awk '{print $NF}')
unset TOKEN
printf '%s\n' "$TOKEN_SHA256"
```

1. Dispatch the workflow with the printed digest as `token_sha256`.
2. While the job is running, download its `ui-session-…` artifact. It contains `connection.json` with the HTTPS URL, target, session ID, and expiry. The job log also displays the URL.
3. Open the URL and enter the raw token from the file to use the browser controller. For an existing agent, give it the paths to `connection.json` and to the private token file on its current machine. Use an existing secure transfer if they are on different machines. Keep token contents out of chat, logs, and evidence.
4. Run the same commands from a fresh client to reconnect. The browser and agent see the same app state. Cancel the workflow to stop early.

```bash
# With GitHub CLI, copy the artifact name from the first command into ARTIFACT.
gh api "repos/$REPO/actions/runs/$RUN_ID/artifacts" --jq '.artifacts[].name'
gh run download "$RUN_ID" --repo "$REPO" --name "$ARTIFACT" --dir live-ui

# Use agent.py from this repository at the same pinned ref as the action.
python3 agent.py live-ui/connection.json --token-file "$TOKEN_FILE" capabilities
python3 agent.py live-ui/connection.json --token-file "$TOKEN_FILE" screenshot before.png
python3 agent.py live-ui/connection.json --token-file "$TOKEN_FILE" action tree.snapshot
```

An agent can inspect the screenshot, use a fresh selector or coordinates, then compare a second capture or assert expected state. If the default iOS Simulator displays a local-network permission prompt for Python, dismiss it with **Don’t Allow** and click inside the Simulator before entering text. See the [agent examples and recovery rules](docs/automation.md).

## Access and verification

To test native peer discovery and communication between GitHub-hosted Android and Apple Silicon iOS, follow the [hosted mobile LAN guide](docs/mobile-lan.md).

Quick Tunnels are the default. Cloudflare terminates HTTPS and gives the job a temporary hostname. Each API request checks the session bearer token. The artifact contains connection metadata. Use dedicated test jobs and synthetic data. The authenticated controller can operate the runner's visible UI. After the time limit or cancellation, the runner closes the listener and tunnel. Remove the private token file when the session ends. [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

The v2 APIs add Unicode text and clipboard, screenshots and recordings, structured commands, batching, and backend capability discovery. Existing v1 clients remain supported, including their ASCII text endpoint. The hosted report includes the target matrix, upstream app pins, workflow links, captured evidence, and gaps. [Five-platform hour and cancellation evidence](verification/v2/lifetime/) · [v2 verification report](verification/v2/README.md) · [original v1 runner checks](verification/README.md)
