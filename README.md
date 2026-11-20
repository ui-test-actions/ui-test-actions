# Live UI test sessions on GitHub Actions

Run your app on a GitHub-hosted runner and control its live UI over HTTPS. The browser controller and HTTP API share the same screen and application state, so you can hand the session to the agent already working with you. Connection uses an ordinary browser or an existing HTTP client. The tunnel connector runs on the GitHub runner.

## Set up the workflow

Start from a [desktop](examples/desktop.yml), [Android](examples/android.yml), or [iOS](examples/ios.yml) workflow. Copy it into `.github/workflows/` and edit the build, launch, and readiness commands for your app. The [desktop proof](.github/workflows/desktop.yml) and [mobile proof](.github/workflows/mobile.yml) show complete hosted workflows with native fixture apps.

| Target | Hosted runner | Application setup |
| --- | --- | --- |
| `linux` | `ubuntu-24.04` | Build your desktop app, then launch it inside the action's X display. The action starts Xvfb if there is no `DISPLAY`. |
| `windows` | `windows-2025` | Build or install your app, then start the GUI executable in the runner's interactive desktop. |
| `macos` | `macos-15` | Build or install the app, then use `open -a /path/to/App.app` or your own launch script. |
| `android` | `ubuntu-24.04` | Boot a KVM-enabled emulator and supply the emulator's ADB serial. Install the APK and launch its activity. |
| `ios` | `macos-26` | Boot an iOS simulator on Apple Silicon. Install a simulator `.app` and launch its bundle ID. The controller drives the visible Simulator window. |

Use Python 3.12 in the job. The action runs `launch` and `ready` in Bash, including on Windows. Start long-running desktop processes in the background and have `launch` return. For a process started in a prior step, omit `launch` and point the action at the existing desktop/device. GitHub's job timeout must cover the build, startup, and full session. [GitHub-hosted runner images and labels](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

### Action inputs

| Input | Meaning |
| --- | --- |
| `target` | Required. One of the targets above. |
| `token-sha256` | Required. Lowercase SHA-256 hex digest of the one-time token. |
| `duration-minutes` | Whole minutes after the readiness check and tunnel startup. Default 15, range 1–180. Use `'60'` for an hour. |
| `launch` | Bash script to start the app. The working directory is the caller's workspace. Omit to attach. |
| `ready` | Bash command polled until it exits zero. Use a genuine readiness test for asynchronous startup. If omitted, the action considers the app ready when launch returns and capture succeeds. |
| `startup-timeout-seconds` | Budget for launch and readiness. Default 180, range 1–1800. |
| `device` | Optional ADB serial or simulator UDID. If omitted, exactly one eligible device must be available. Keep only the selected iOS Simulator window in use. |

## Connect from your machine

Generate a new token for each run. The Bash example uses existing OpenSSL and saves the token in a private temporary file on the machine running the client.

```bash
TOKEN_FILE=$(mktemp)
TOKEN=$(openssl rand -hex 32)
printf '%s\n' "$TOKEN" > "$TOKEN_FILE"
TOKEN_SHA256=$(printf '%s' "$TOKEN" | openssl dgst -sha256 | awk '{print $NF}')
printf '%s\n' "$TOKEN_SHA256"
```

1. Launch the workflow from GitHub's **Actions → Run workflow** and enter `TOKEN_SHA256` in `token_sha256`. The workflow receives the digest. Keep the original token on the client.
2. While the job is running, download its `ui-session-…` artifact from the run page and open `connection.json`. It contains the HTTPS address, target, session ID, and expiry. You can also find the URL in the **Open UI session** step. If you have GitHub CLI, the commands below retrieve the same artifact while the job is live.
3. Open the HTTPS address in your browser. Enter the original token, then use the displayed screenshot to click, tap, or drag. To type, select a field on the runner first and submit text through the controller. Use **Refresh screenshot** after an app animation or other delayed change.
   On iOS, click inside the visible Simulator window. During verification, macOS showed a local-network permission prompt for Python. Dismissing it with **Don’t Allow** left the session working.
4. Open the same address and enter the same token to reconnect. The app state is shared between connections. Cancel the job to end the session early.

```bash
REPO=owner/consumer-repo
RUN_ID=123456789
gh api "repos/$REPO/actions/runs/$RUN_ID/artifacts" --jq '.artifacts[].name'
ARTIFACT=ui-session-interactive-1-REPLACE_WITH_SESSION_ID
gh run download "$RUN_ID" --repo "$REPO" --name "$ARTIFACT" --dir ./live-ui
cat ./live-ui/connection.json
```

## Give the existing agent access

Tell the agent the URL and the path to the private token file **on the machine where it runs**. If you generated the token on another machine, use an existing secure transfer, such as your existing SSH connection, to put it in a mode-`0600` file there. The agent can use the terminal commands below in the current session and open each saved PNG with its existing image viewer. Example instruction to the agent:

> Connect to this live UI session using the HTTPS URL and the token at the private file path I supplied. Read a screenshot, choose coordinates based on what you see, send one UI action, then read a fresh screenshot and decide what to do next. Keep the token out of tool output and chat.

```bash
URL=https://REPLACE_WITH_THE_HOST_FROM_CONNECTION_JSON.trycloudflare.com
# TOKEN_FILE points to the private token file on this machine.
TOKEN=$(<"$TOKEN_FILE")
ui() {
  printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" |
    curl --silent --show-error --max-time 20 --proto '=https' --config - "$@"
}

ui --fail "$URL/v1/session"
ui --fail "$URL/v1/screenshot" -o before.png
# Inspect before.png and replace the example coordinates with those you see.
ui --fail -H 'Content-Type: application/json' \
  --data '{"action":"click","x":320,"y":180}' "$URL/v1/input"
ui --fail -H 'Content-Type: application/json' \
  --data '{"action":"type","text":"External agent proof"}' "$URL/v1/input"
ui --fail "$URL/v1/screenshot" -o after.png
```

- `GET /v1/session` returns the session ID, target, and seconds remaining.
- `GET /v1/screenshot` returns the current PNG. Use its top-left pixel as `(0,0)`. Get a fresh image if the app rotates or the display changes.
- `POST /v1/input` accepts `{"action":"click","x":320,"y":180}` for a click or tap, and `{"action":"type","text":"hello"}` for up to 256 printable ASCII characters in the focused field.
- To swipe on mobile or drag on desktop, send `{"action":"swipe","x":300,"y":600,"end_x":300,"end_y":300,"duration_ms":400}`. Duration is 100–3000 ms. Wait for the response and any app animation before getting another screenshot.

## Access and expiry

The managed [Cloudflare Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) forwards HTTPS traffic to the session's loopback listener. It requires no Cloudflare account. Cloudflare terminates HTTPS and Quick Tunnels have no availability SLA. The public URL is a locator. Every screen, input, and session API request checks the bearer token, which is held in the browser tab or the local terminal. The connection artifact contains only the HTTPS address, target, session ID, and expiry. Use non-production test data and avoid leaving sensitive screens in the test desktop.

The action stops the listener and tunnel when the timer expires. GitHub job cancellation stops the hold step, which signals the runner-side session to close. A successful reconnect during the live window returns the same session ID. When the job is over, the endpoint is unreachable or returns an error. Remove your local token file after use.

## Hosted verification

See the [hosted runner proofs](verification/README.md) for run links, screenshots, and external connection checks.
