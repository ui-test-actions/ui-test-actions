# UI session transports

Use the same [UI API](automation.md) and client with every transport. The action publishes the selected transport, origin, session ID and expiration in `connection.json`. Use the client from the same revision as the action and obtain the artifact directly from the GitHub run you started. Your one-time session bearer stays in a private file on the controller. The action receives only its SHA-256 digest.

| Input `transport` | Use it when | Prerequisites | Endpoint |
| --- | --- | --- | --- |
| `auto` or `cloudflare-quick` | You want to connect from an existing machine with no networking setup | Runner Internet access to GitHub and Cloudflare. `auto` also recognizes the original Named Tunnel inputs. | Temporary Cloudflare HTTPS hostname |
| `cloudflare-named` | You operate a dedicated hostname and optionally use Cloudflare Access | A remotely managed tunnel, DNS route and GitHub Actions connector secret | Fixed Cloudflare HTTPS hostname |
| `private` | The runner and controller can reach each other over an existing private network | A runner-assigned RFC 1918 or CGNAT IPv4 address, a scoped route or overlay, and OpenSSL on the runner | Direct HTTPS on the selected address and port, with a certificate issued per session |
| `local` | The observer runs on the runner itself | Start the observer before the blocking action, as a background process in the same job | HTTP on `127.0.0.1` with an assigned port |

The transport carries screenshots and control requests. The Android/iOS app LAN has its own interfaces, routes, discovery traffic, and credentials. Selecting a transport does not reconfigure those networks. The [mobile LAN workflow](mobile-lan.md) keeps its own relay and interface lifecycle.

The same release supports all four transports. Use `v3.0.1` or its full Action commit from the [release page](https://github.com/ui-test-actions/ui-test-actions/releases/tag/v3.0.1). In the snippets below, declare `token_sha256` as a required string dispatch input, set up Python 3.12 earlier in the job, and use your app's existing Bash launch and readiness commands.

## Quick Tunnel

This is the default. No Cloudflare account, custom domain, client installation or GitHub network secret is required. Download the live artifact and follow the [agent connection guide](../README.md#connect-and-hand-the-session-to-an-agent).

```yaml
- uses: ui-test-actions/ui-test-actions@v3.0.1
  with:
    target: linux
    token-sha256: ${{ inputs.token_sha256 }}
    duration-minutes: '60'
    launch: bash ci/launch-app.sh
    ready: bash ci/check-ready.sh
```

Cloudflare terminates HTTPS at its edge. The action verifies the HTTPS route reaches this runner before publishing it. If the runner resolver has a stale negative answer for a new Quick Tunnel hostname, the readiness probe uses Cloudflare DNS over HTTPS and still checks the original hostname's TLS certificate. Quick Tunnels have no provider uptime guarantee and use changing hostnames. A live connector can reconnect upstream. If its process exits, the action closes the session and the job reports a transport failure. Start a fresh run with a fresh bearer. [Cloudflare Quick Tunnel limits](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) · [Cloudflare DNS over HTTPS](https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/)

Set `transport-fallback: local` only when a same-job observer is useful if Quick Tunnel startup fails. This allows the action to publish loopback after all connector attempts fail and the failed connector shuts down. The artifact tells the observer which transport opened. Fallback happens before the action publishes an origin. A Named Tunnel or private configuration fails closed. The default fallback is `none`.

## Named Tunnel and Access

In Cloudflare, create a dedicated remotely managed tunnel. Publish your assigned hostname with service `http://127.0.0.1:8787`. Keep the connector token in the GitHub Actions secret `CLOUDFLARE_TUNNEL_TOKEN`. Use one active connector for a hostname during a session. If you share the hostname across workflows in the same repository, use the same concurrency group. Use separate hostnames for parallel sessions or separate repositories. Cloudflare can route requests among replicas of the same tunnel. [Cloudflare routes and replicas](https://developers.cloudflare.com/tunnel/configuration/)

Add the concurrency group at workflow level.

```yaml
concurrency:
  group: ui-test-named-${{ vars.UI_TEST_TUNNEL_HOSTNAME }}
  cancel-in-progress: false
```

```yaml
- uses: ui-test-actions/ui-test-actions@v3.0.1
  with:
    target: linux
    transport: cloudflare-named
    token-sha256: ${{ inputs.token_sha256 }}
    tunnel-hostname: ${{ vars.UI_TEST_TUNNEL_HOSTNAME }}
    tunnel-token: ${{ secrets.CLOUDFLARE_TUNNEL_TOKEN }}
    origin-port: '8787'
    access-client-id: ${{ secrets.CLOUDFLARE_ACCESS_CLIENT_ID }}
    access-client-secret: ${{ secrets.CLOUDFLARE_ACCESS_CLIENT_SECRET }}
    launch: bash ci/launch-app.sh
    ready: bash ci/check-ready.sh
```

For Access, create a self-hosted application covering the entire hostname and use a Service Auth policy for a dedicated service token. Store its credential pair in the Actions secrets shown above. During startup the action requires the anonymous probe to be denied at the edge and a probe with service headers to reach the exact live origin. The probes carry no UI bearer. Omit both Access inputs for a route protected solely by the UI bearer. Use the two Cloudflare service headers so the UI bearer can still use `Authorization`. [Cloudflare Access service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)

Use the client from the Named example's pin. The readiness probe and API client send `User-Agent: ui-test-actions/2` to identify themselves to Cloudflare. A prior pin used Python's default HTTP identifier, which the test zone rejected with error 1010 before checking the service token. [Cloudflare error 1010](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/)

Give automated clients a private JSON file with keys `client_id` and `client_secret`, and pass it separately from the UI bearer:

```bash
python3 agent.py live-ui/connection.json --token-file "$TOKEN_FILE" --access-file "$ACCESS_FILE" capabilities
```

For the embedded browser client, configure an appropriate interactive Access policy and sign in to it in that browser first. A dedicated Named Tunnel can restart its connector at the same hostname with the same UI session and original expiry. The app receives neither the connector token nor the runner's Access probe credentials. The route in your Cloudflare account remains configured after the session, with the job's connector and listener closed. See the [live acceptance procedure](external-acceptance.md#cloudflare-named-tunnel-and-access).

## Private networking

Join the runner and the existing agent machine to an authorized private overlay before using the action. The origin binds only the assigned address. The action does not create overlay routes or change the runner's DNS. Use overlay ACLs to allow only your controller to reach the session port, and provision a distinct ephemeral runner identity per job. The private adapter accepts routed IPv4 addresses in RFC 1918 or `100.64.0.0/10`.

### Tailscale example

The example uses the official Tailscale Action with a federated identity and an ephemeral runner tag. Provision a tagged GitHub identity scoped to the trusted repository and workflow, and grant your agent's identity access to that tag on TCP port 8787. Add the GitHub job permission `id-token: write` and restrict other job permissions to what your workflow needs. Keep the agent machine joined to the same tailnet. An OAuth example can use the same action with `oauth-secret: ${{ secrets.TS_OAUTH_SECRET }}` and omit `audience`. [Tailscale Action and credential setup](https://tailscale.com/docs/integrations/github/github-action) · [Tailscale grants](https://tailscale.com/docs/reference/syntax/grants)

```yaml
- uses: tailscale/github-action@064b10558093f38325e838ddea35486bdc6b1d5c
  with:
    oauth-client-id: ${{ secrets.TS_OAUTH_CLIENT_ID }}
    audience: ${{ secrets.TS_AUDIENCE }}
    tags: tag:ui-ci
    args: --accept-dns=false --accept-routes=false
- id: overlay
  shell: bash
  run: printf 'ip=%s\n' "$(tailscale ip -4)" >> "$GITHUB_OUTPUT"
- uses: ui-test-actions/ui-test-actions@v3.0.1
  with:
    transport: private
    private-address: ${{ steps.overlay.outputs.ip }}
    origin-port: '8787'
    target: linux
    token-sha256: ${{ inputs.token_sha256 }}
    launch: bash ci/launch-app.sh
    ready: bash ci/check-ready.sh
```

The official Tailscale Action currently installs on hosted Linux. If you already provision a WireGuard interface, substitute its runner address for the output from the overlay step. The action's private mode does not need Tailscale Serve, Funnel, MagicDNS, or a public DNS certificate. The standard agent client pins the per-session certificate from the GitHub artifact and verifies the IPv4 SAN. Use the [local agent dashboard](dashboard.md) if you need browser inspection without importing a new certificate into the browser. With other clients, use the exact PEM from `ca_pem` as a trust anchor and keep verification enabled. The PEM is public. The signing key is generated on the runner and removed from disk after Python loads it.

### Same-runner access

When only a process on the runner needs UI access, use `local`. A process elsewhere cannot reach a GitHub runner using its advertised loopback URL. Start the observer before the action because the action holds its caller's step open. The [hosted transport workflow](../.github/workflows/transports.yml) includes a working Bash example with a background observer and a private bearer generated in that job.

```yaml
- uses: ui-test-actions/ui-test-actions@v3.0.1
  with:
    transport: local
    target: linux
    token-sha256: ${{ inputs.token_sha256 }}
    launch: bash ci/launch-app.sh
    ready: bash ci/check-ready.sh
```

## Reconnect and verify

Use the same trusted artifact and private token file to reconnect. Each official client request includes the session ID when the artifact carries it. The runner rejects a request addressed to a different session even if its bearer is accepted. Parallel jobs need different tokens. The action stops the API listener at expiry or cancellation and tracks the GitHub hold step with a watchdog. Use the live `seconds_remaining` countdown for timing-sensitive work. The artifact's `expires_unix` is a wall-clock estimate from the runner.

The Python client retries transient failures on reads and retries a command when the runner explicitly reports `session_busy` before dispatch. If a mutation loses its response, it returns `action_outcome_unknown` with the original request ID when available. Inspect the live result before retrying. In the same session, a resend with the same ID and arguments returns the cached response or `replay_unavailable` without repeating the mutation. The legacy input endpoint has no replay IDs. The browser controller uses the same bearer and refuses redirects on API requests.

[Hosted results and provider-specific limits](../verification/transports/README.md)

## Provider interface

The session lifecycle owns the app, API authentication, action replay protection and lease. An adapter supplies the socket binding and optional TLS context and reports the origin after setup. It can maintain its connector until the existing deadline and releases its resources during close. New adapter code can implement that contract without changing the UI automation API or the application LAN.
