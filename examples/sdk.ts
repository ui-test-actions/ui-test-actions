import { writeFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import { UiTestClient } from "../sdk/typescript/index.ts"

const [sessions, device, output] = process.argv.slice(2)
if (!sessions || !device || !output) {
  throw new Error("Usage: node examples/sdk.ts sessions.json linux screenshot.png")
}

const client = await UiTestClient.open({ sessions, server: fileURLToPath(new URL("../mcp_server.py", import.meta.url)) })
try {
  const devices = await client.sessions()
  const available = devices.find((item) => item.device === device && item.available)
  if (!available) throw new Error("That device is unavailable")
  const info = await client.capabilities(device)
  await writeFile(output, await client.screenshot(device), { flag: "wx" })
  console.log(JSON.stringify({ target: info.target, commands: Object.keys(info.commands), saved: output }))
} finally {
  client.close()
}
