import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process"
import { createInterface } from "node:readline"

export type Json = null | boolean | number | string | Json[] | { [name: string]: Json }
export type Params = { [name: string]: Json }
export type UiAction = { command: string; params?: Params }
export type Target = "linux" | "windows" | "macos" | "android" | "ios"
export type LiveDevice =
  | { device: string; available: true; target: Target; seconds_remaining: number }
  | { device: string; available: false; http_status: number | null }
export type Capabilities = { api_version: number; target: Target; commands: Record<string, Params> }
export type Result = { ok: boolean; command?: string; result?: Params; error?: Params }
export type Options = {
  sessions: string
  server: string
  python?: string
  outputRoot?: string
  timeoutMs?: number
}

type ToolResponse = {
  content: { type: string; data?: string; mimeType?: string }[]
  structuredContent: Params
  isError?: boolean
}
type Reply = { id: number; result?: unknown; error?: { code: number; message: string } }
type Pending = { resolve: (value: unknown) => void; reject: (error: Error) => void; timer: NodeJS.Timeout }

export class UiError extends Error {
  readonly details: Params
  constructor(message: string, details: Params) {
    super(message)
    this.name = "UiError"
    this.details = details
  }
}

export class UiTestClient {
  private readonly child: ChildProcessWithoutNullStreams
  private readonly calls = new Map<number, Pending>()
  private readonly timeout: number
  private sequence = 0
  private ended = false

  private constructor(options: Options) {
    this.timeout = options.timeoutMs ?? 120_000
    if (!Number.isInteger(this.timeout) || this.timeout < 100 || this.timeout > 1_800_000) {
      throw new RangeError("timeoutMs must be between 100 and 1800000")
    }
    const args = [options.server, "--sessions", options.sessions]
    if (options.outputRoot) args.push("--output-root", options.outputRoot)
    this.child = spawn(options.python ?? "python3", args, { stdio: "pipe" })
    this.child.stderr.resume()
    this.child.stdin.on("error", () => this.disconnect("MCP input closed"))
    this.child.on("error", () => this.disconnect("Could not start the UI MCP server"))
    this.child.on("close", () => this.disconnect("The UI MCP server closed"))
    createInterface({ input: this.child.stdout }).on("line", (line) => {
      let response: Reply
      try {
        response = JSON.parse(line) as Reply
      } catch {
        this.disconnect("Invalid MCP response")
        return
      }
      const pending = this.calls.get(response?.id)
      if (!pending) return
      clearTimeout(pending.timer)
      this.calls.delete(response.id)
      if (response.error) pending.reject(new UiError(response.error.message, { code: response.error.code }))
      else pending.resolve(response.result)
    })
  }

  static async open(options: Options): Promise<UiTestClient> {
    const client = new UiTestClient(options)
    try {
      const value = await client.request("initialize", {
        protocolVersion: "2025-11-25",
        capabilities: {},
        clientInfo: { name: "ui-test-actions-typescript", version: "1.0.0" },
      }) as { protocolVersion: string }
      if (value.protocolVersion !== "2025-11-25") {
        throw new UiError("Unsupported MCP protocol version", { code: "unsupported_version" })
      }
      client.child.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n")
      return client
    } catch (error) {
      client.close()
      throw error
    }
  }

  private disconnect(message: string) {
    if (this.ended) return
    this.ended = true
    for (const value of this.calls.values()) {
      clearTimeout(value.timer)
      value.reject(new UiError(message, { code: "connection_closed" }))
    }
    this.calls.clear()
    this.child.stdin.end()
  }

  close() {
    this.disconnect("The UI MCP client was closed")
    if (this.child.exitCode === null && this.child.signalCode === null) this.child.kill()
  }

  private request(method: string, params: object): Promise<unknown> {
    if (this.ended) return Promise.reject(new UiError("The UI MCP client is closed", { code: "connection_closed" }))
    const id = ++this.sequence
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.calls.delete(id)
        reject(new UiError("The UI command timed out", { code: "timeout" }))
      }, this.timeout)
      this.calls.set(id, { resolve, reject, timer })
      this.child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n")
    })
  }

  private async tool(name: string, args: object = {}): Promise<ToolResponse> {
    const response = await this.request("tools/call", { name, arguments: args }) as ToolResponse
    if (response.isError) {
      const details = response.structuredContent
      throw new UiError(typeof details.message === "string" ? details.message : "UI command failed", details)
    }
    return response
  }

  async sessions(): Promise<LiveDevice[]> {
    const response = (await this.tool("ui_sessions")).structuredContent
    return response.sessions as LiveDevice[]
  }

  async capabilities(device: string): Promise<Capabilities> {
    return (await this.tool("ui_capabilities", { device })).structuredContent as unknown as Capabilities
  }

  async screenshot(device: string): Promise<Buffer> {
    const response = await this.tool("ui_screenshot", { device })
    const image = response.content.find((item) => item.type === "image" && item.mimeType === "image/png")
    if (!image?.data) throw new UiError("MCP returned no screenshot", { code: "capture_unavailable" })
    return Buffer.from(image.data, "base64")
  }

  async inspect(device: string, limit = 200): Promise<Result> {
    return (await this.tool("ui_inspect", { device, limit })).structuredContent as Result
  }

  async action(device: string, command: string, params: Params = {}, requestId?: string): Promise<Result> {
    return (await this.tool("ui_action", { device, command, params, request_id: requestId })).structuredContent as Result
  }

  async batch(device: string, steps: UiAction[], requestId?: string): Promise<Params> {
    return (await this.tool("ui_batch", { device, steps, request_id: requestId })).structuredContent
  }

  async assert(device: string, expect: Params): Promise<void> {
    await this.tool("ui_assert", { device, expect })
  }

  async workflow(device: string, workflow: Params, inputs: Params = {}): Promise<Params> {
    return (await this.tool("ui_workflow", { device, workflow, inputs })).structuredContent
  }

  async coordinate(scenario: Params, inputs: Params = {}): Promise<Params> {
    return (await this.tool("ui_coordinate", { scenario, inputs })).structuredContent
  }
}
