const $ = (id) => document.getElementById(id)
const fragment = new URLSearchParams(location.hash.slice(1)).get("access")
if (fragment) {
  sessionStorage.setItem("ui-inspector-access", fragment)
  history.replaceState(null, "", location.pathname)
}
const access = sessionStorage.getItem("ui-inspector-access")
let active
let capabilities = {}
let observed
let screenshotUrl
let evidenceUrl
const captures = new Set()
let live = false
let selectedRun
let pointer

async function request(path, body, binary = false) {
  const headers = { Authorization: "Bearer " + access }
  if (body !== undefined) headers["Content-Type"] = "application/json"
  const response = await fetch("/api/" + path, {
    method: body === undefined ? "GET" : "POST",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.error?.message ?? "Request failed (" + response.status + ")")
  }
  return binary ? response.blob() : response.json()
}

function notice(text) { $("notice").textContent = text }
function show(value, title = "Results") {
  $("result-title").textContent = title
  $("result").textContent = JSON.stringify(value, null, 2)
}
function handle(error) { notice(error.message) }
function devicePath(name, operation) { return "device/" + encodeURIComponent(name) + "/" + operation }
function button(label, detail, execute) {
  const element = document.createElement("button")
  element.type = "button"
  element.textContent = label
  if (detail !== undefined) {
    const status = document.createElement("small")
    status.textContent = detail
    element.append(status)
  }
  element.addEventListener("click", () => Promise.resolve().then(execute).catch(handle))
  return element
}

async function listDevices() {
  const { sessions } = await request("devices")
  const items = sessions.map((session) => {
    const remaining = session.available ? Math.max(0, session.seconds_remaining) : 0
    const time = remaining > 60 ? Math.ceil(remaining / 60) + " min" : remaining + " sec"
    const label = session.target === session.device || !session.target ? session.device :
      session.device + " · " + session.target
    const item = button(label, session.available ? time : "Unavailable", () => choose(session.device))
    item.disabled = !session.available
    item.setAttribute("aria-pressed", String(active === session.device))
    if (session.available) item.querySelector("small").classList.add("available")
    return item
  })
  $("devices").replaceChildren(...items)
  const liveCount = sessions.filter((session) => session.available).length
  if (liveCount === 0) notice("There are no reachable sessions")
  else if (!active) notice("Select a device · " + liveCount + " available")
}

async function choose(name) {
  active = name
  pointer = undefined
  observed = undefined
  $("tree").replaceChildren()
  $("screen").hidden = true
  $("screen-empty").hidden = false
  $("screen-empty").textContent = "Capturing " + name
  $("screen-title").textContent = name + " live screen"
  const data = await request(devicePath(name, "capabilities"))
  if (active !== name) return
  capabilities = data.commands
  $("command").replaceChildren(...Object.keys(capabilities).sort().map((command) => new Option(command, command)))
  changeCommand()
  for (const control of ["refresh-screen", "live", "command", "execute", "diagnostics", "run"]) $(control).disabled = false
  $("touch").disabled = !capabilities["pointer.click"]
  $("inspect").disabled = !capabilities["tree.snapshot"]
  $("search").disabled = $("inspect").disabled
  $("screen").classList.toggle("controllable", $("touch").checked && !$("touch").disabled)
  notice("Connected · " + name)
  await Promise.all([capture(), listDevices()])
}

function changeCommand() {
  const selected = capabilities[$("command").value]
  const required = selected?.required ?? []
  $("shape").textContent = required.length ? "Required · " + required.join(", ") : "No required arguments"
  $("params").value = "{}"
}

async function capture() {
  const name = active
  if (!name || captures.has(name)) return
  captures.add(name)
  try {
    const blob = await request(devicePath(name, "screenshot"), undefined, true)
    if (active !== name) return
    if (screenshotUrl) URL.revokeObjectURL(screenshotUrl)
    screenshotUrl = URL.createObjectURL(blob)
    $("screen").src = screenshotUrl
    $("screen").hidden = false
    $("screen-empty").hidden = true
  } finally {
    captures.delete(name)
  }
}

async function action(command, params) {
  const name = active
  if (!name) return
  const request_id = typeof crypto.randomUUID === "function" ? crypto.randomUUID() :
    Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join("")
  const reply = await request(devicePath(name, "action"), { command, params, request_id })
  show(reply, command)
  if (command === "recording.stop" && reply.ok) {
    const image = await request(devicePath(name, "recording"), undefined, true)
    if (evidenceUrl) URL.revokeObjectURL(evidenceUrl)
    evidenceUrl = URL.createObjectURL(image)
    $("evidence").src = evidenceUrl
    $("evidence").alt = "Latest session recording"
    $("evidence").hidden = false
  }
  if (command.startsWith("pointer.") || command === "element.click" || command.startsWith("keyboard.") ||
      command.startsWith("text.") || command.startsWith("app.") || command.startsWith("device.")) {
    observed = undefined
    renderTree()
    await capture()
  }
}

function renderTree() {
  const query = $("search").value.trim().toLowerCase()
  const snapshot = observed?.snapshot_id
  const rows = (observed?.nodes ?? []).filter((node) => node.visible !== false).flatMap((node) => {
    const title = node.text || node.name || node.resource_id || node.role
    if (!title || (query && !String(title).toLowerCase().includes(query))) return []
    const row = button(String(title), node.role, () => action("element.click", {
      id: node.id, snapshot_id: snapshot,
    }))
    row.disabled = !capabilities["element.click"] || node.enabled === false || !node.id
    return [row]
  })
  $("tree").replaceChildren(...rows)
}

async function inspect() {
  const name = active
  const reply = await request(devicePath(name, "tree"))
  if (active !== name) return
  observed = reply.result
  renderTree()
  notice(observed.nodes.length + " elements · " + name + (observed.truncated ? " · partial tree" : ""))
}

function point(event) {
  const image = $("screen")
  const bounds = image.getBoundingClientRect()
  const coordinate = (value, start, rendered, length) =>
    Math.max(0, Math.min(length - 1, Math.floor((value - start) * length / rendered)))
  return { x: coordinate(event.clientX, bounds.left, bounds.width, image.naturalWidth),
    y: coordinate(event.clientY, bounds.top, bounds.height, image.naturalHeight) }
}

async function listHistory() {
  const { runs } = await request("history")
  $("history").replaceChildren(...runs.map((run) => {
    const clock = new Date(run.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    const item = button((run.device ?? "Devices") + " · " + clock, run.status, () => openRun(run.id))
    item.setAttribute("aria-pressed", String(run.id === selectedRun))
    return item
  }))
}

async function openRun(id) {
  selectedRun = id
  const value = await request("history/" + id)
  if (selectedRun !== id) return
  show(value.report ?? value.summary, "Run · " + value.summary.status)
  $("artifacts").replaceChildren(...value.artifacts.map((name) => button(name, undefined, async () => {
    const image = await request("history/" + id + "/" + name, undefined, true)
    if (selectedRun !== id) return
    if (evidenceUrl) URL.revokeObjectURL(evidenceUrl)
    evidenceUrl = URL.createObjectURL(image)
    $("evidence").src = evidenceUrl
    $("evidence").alt = "Selected run screenshot"
    $("evidence").hidden = false
  })))
  if (value.summary.status === "running") setTimeout(() => {
    if (selectedRun === id) openRun(id).catch(handle)
  }, 1600)
  else await listHistory()
}

$("screen").draggable = false
$("screen").addEventListener("load", () => {
  $("dimensions").textContent = $("screen").naturalWidth + " × " + $("screen").naturalHeight
})
$("screen").addEventListener("pointerdown", (event) => {
  if ($("touch").checked && !$("touch").disabled && $("screen").naturalWidth) {
    pointer = { ...point(event), origin: active, time: performance.now() }
    $("screen").setPointerCapture(event.pointerId)
  }
})
$("screen").addEventListener("pointerup", (event) => {
  if (!pointer || active !== pointer.origin) return
  const start = pointer
  pointer = undefined
  const end = point(event)
  if (capabilities["pointer.drag"] && Math.hypot(start.x - end.x, start.y - end.y) > 12) {
    action("pointer.drag", { x: start.x, y: start.y, end_x: end.x, end_y: end.y,
      duration_ms: Math.max(100, Math.min(3000, Math.round(performance.now() - start.time))) }).catch(handle)
  } else action("pointer.click", end).catch(handle)
})
$("screen").addEventListener("pointercancel", () => { pointer = undefined })
$("touch").addEventListener("change", () => $("screen").classList.toggle("controllable", $("touch").checked))
$("command").addEventListener("change", changeCommand)
$("search").addEventListener("input", renderTree)
$("refresh-devices").onclick = () => listDevices().catch(handle)
$("refresh-history").onclick = () => listHistory().catch(handle)
$("refresh-screen").onclick = () => capture().catch(handle)
$("inspect").onclick = () => inspect().catch(handle)
$("diagnostics").onclick = () => request(devicePath(active, "diagnostics")).then((data) => show(data, "Diagnostics")).catch(handle)
$("execute").onclick = () => Promise.resolve().then(() => action($("command").value, JSON.parse($("params").value))).catch(handle)
$("live").onclick = () => {
  live = !live
  $("live").setAttribute("aria-pressed", String(live))
  if (live) capture().catch(handle)
}
$("run").onclick = () => Promise.resolve().then(async () => {
  const mode = $("mode").value
  const body = { mode, definition: JSON.parse($("definition").value), inputs: JSON.parse($("inputs").value) }
  if (mode === "workflow") body.device = active
  const run = await request("run", body)
  $("evidence").hidden = true
  await listHistory()
  await openRun(run.id)
}).catch(handle)

if (!access) notice("Open the private link printed by the dashboard command")
else {
  Promise.all([listDevices(), listHistory()]).catch(handle)
  setInterval(() => {
    if (live && !document.hidden) capture().catch(handle)
  }, 1700)
  setInterval(() => {
    if (!document.hidden) listDevices().catch(handle)
  }, 15000)
}
