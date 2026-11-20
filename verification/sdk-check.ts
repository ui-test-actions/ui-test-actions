import { readFile, writeFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import { UiTestClient } from "../sdk/typescript/index.ts"

const [sessions, output] = process.argv.slice(2)
if (!sessions || !output) throw new Error("Expected a private session registry and an evidence directory")
const client = await UiTestClient.open({ sessions, server: fileURLToPath(new URL("../mcp_server.py", import.meta.url)) })
try {
  const viewport = JSON.parse(await readFile(`${output}/windows-target.json`, "utf8"))
  const info = await client.capabilities("windows")
  if (info.target !== "windows" || info.api_version !== 2) throw new Error("Unexpected target")
  const result = await client.batch("windows", [{ command: "pointer.click", params: viewport.click }], "ts-sdk-click")
  if (result.ok !== true) throw new Error("Fixture click failed")
  await client.assert("windows", { pixel: viewport.pixel })
  await writeFile(`${output}/windows-after.png`, await client.screenshot("windows"), { flag: "wx" })
  const clipboard = await client.action("windows", "clipboard.get")
  if (clipboard.result?.text !== "مرحبًا ١٢٣ — SDK 🌍") throw new Error("Clipboard did not retain the exact value")
  await writeFile(`${output}/typescript.json`, JSON.stringify({
    target: info.target, action: "pointer.click", pixel: viewport.pixel, clipboard_verified: true,
  }, null, 2) + "\n", { flag: "wx" })
} finally {
  client.close()
}
