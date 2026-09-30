"""Small Home Assistant Ingress UI for Better GroBro battery assignment."""

from __future__ import annotations

import json
import logging
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from grobro.ha.battery_position import (
    AUTO_ASSIGNMENT,
    EMPTY_ASSIGNMENT,
    _is_plausible_serial,
    load_battery_ui_state,
    save_manual_assignments,
)

LOG = logging.getLogger(__name__)
INGRESS_PORT = int(os.getenv("INGRESS_PORT", "8099"))
_ALLOWED_CLIENTS = {"172.30.32.2", "127.0.0.1", "::1"}

_INDEX_HTML = r"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Better GroBro – Batterie-Zuordnung</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #101418;
      --card: #1c2228;
      --border: #343b43;
      --text: #e8eaed;
      --muted: #aeb6bf;
      --accent: #03a9f4;
      --danger: #ff6b6b;
      --ok: #62c96b;
      --secondary: #2a3138;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    main { max-width: 980px; margin: 0 auto; padding: 24px; }
    h1 { margin: 0 0 6px; font-size: 26px; }
    h2 { margin: 0 0 16px; font-size: 18px; }
    p { margin: 0; }
    .muted { color: var(--muted); }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 18px;
      margin-top: 18px;
    }
    .row {
      display: grid;
      grid-template-columns: minmax(180px, 1fr) minmax(280px, 1.4fr);
      gap: 18px;
      align-items: center;
      padding: 12px 0;
      border-top: 1px solid var(--border);
    }
    .row:first-of-type { border-top: 0; }
    label { font-weight: 600; }
    select, button {
      width: 100%;
      min-height: 42px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: #151a1f;
      color: var(--text);
      padding: 8px 12px;
      font: inherit;
    }
    button {
      width: auto;
      min-width: 130px;
      cursor: pointer;
      background: var(--accent);
      color: #00131d;
      border-color: transparent;
      font-weight: 700;
    }
    button.secondary {
      background: var(--secondary);
      color: var(--text);
      border-color: var(--border);
    }
    button:disabled { opacity: .55; cursor: default; }
    .page-toolbar {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }
    .toolbar { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; }
    .toolbar > div { min-width: 280px; flex: 1; }
    .status {
      margin-top: 14px;
      border-radius: 8px;
      padding: 10px 12px;
      border: 1px solid var(--border);
    }
    .status.ok { border-color: var(--ok); }
    .status.error { border-color: var(--danger); color: #ffd2d2; }
    .warning {
      border-color: #c58b16;
      background: #2a2417;
    }
    .serials {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 10px;
    }
    .chip {
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 5px 9px;
      color: var(--muted);
    }
    .right {
      display: flex;
      justify-content: flex-end;
      margin-top: 16px;
      gap: 12px;
      flex-wrap: wrap;
    }
    .small-note {
      margin-top: 10px;
      font-size: 12px;
      color: var(--muted);
    }
    @media (max-width: 700px) {
      main { padding: 16px; }
      .row { grid-template-columns: 1fr; gap: 8px; }
      .toolbar > div { min-width: 100%; }
      button { width: 100%; }
      .page-toolbar { flex-direction: column; align-items: stretch; }
      .right { justify-content: stretch; }
    }
  </style>
</head>
<body>
<main>
  <div class="page-toolbar">
    <div>
      <h1>Better GroBro</h1>
      <p class="muted">Manuelle Batterie-Zuordnung für NOAH und NEXA</p>
    </div>
    <button id="back-top" type="button" class="secondary">Zurück zum Add-on</button>
  </div>

  <section class="card">
    <div class="toolbar">
      <div>
        <label for="device">Gerät</label>
        <select id="device"></select>
      </div>
      <button id="refresh" type="button">Aktualisieren</button>
    </div>
    <div id="feature-warning" class="status warning" hidden>
      KEEP_BATTERY_POSITION ist deaktiviert. Manuelle Zuordnungen bleiben aktiv;
      „Automatisch“ folgt dann der aktuell vom Gerät gemeldeten Position.
    </div>
    <div id="detected" class="serials"></div>
  </section>

  <section class="card">
    <h2>Positionen</h2>
    <div class="row">
      <div>
        <label for="slot2">Bat2</label>
        <div id="auto2" class="muted"></div>
      </div>
      <select id="slot2"></select>
    </div>
    <div class="row">
      <div>
        <label for="slot3">Bat3</label>
        <div id="auto3" class="muted"></div>
      </div>
      <select id="slot3"></select>
    </div>
    <div class="row">
      <div>
        <label for="slot4">Bat4</label>
        <div id="auto4" class="muted"></div>
      </div>
      <select id="slot4"></select>
    </div>
    <div class="right">
      <button id="back-bottom" type="button" class="secondary">Zurück</button>
      <button id="save" type="button">Speichern</button>
    </div>
    <div class="small-note">
      Nach erfolgreichem Speichern wirst du automatisch zur Add-on-Hauptansicht zurückgeführt.
    </div>
    <div id="message" class="status" hidden></div>
  </section>
</main>

<script>
const AUTO = "__auto__";
const EMPTY = "__empty__";
let state = null;

function apiUrl(suffix) {
  const path = window.location.pathname.replace(/\/+$/, "");
  return path + "/" + suffix.replace(/^\/+/, "");
}

function option(value, label, selected) {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = label;
  item.selected = selected;
  return item;
}

function currentDevice() {
  if (!state) return null;
  const id = document.getElementById("device").value;
  return state.devices.find((device) => device.device_id === id) || null;
}

function goBackToAddon() {
  try {
    if (window.history.length > 1) {
      window.history.back();
    }
  } catch (error) {
    console.warn("history.back() failed", error);
  }
}

function renderAssignments() {
  const device = currentDevice();
  const controls = [2, 3, 4].map((slot) => document.getElementById("slot" + slot));
  document.getElementById("save").disabled = !device;
  document.getElementById("detected").replaceChildren();

  if (!device) {
    for (const control of controls) {
      control.replaceChildren(option(AUTO, "Automatisch", true));
      control.disabled = true;
    }
    return;
  }

  for (const entry of device.detected) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = entry.serial + " (physisch Bat" + entry.physical_slot + ")";
    document.getElementById("detected").appendChild(chip);
  }

  for (const slot of [2, 3, 4]) {
    const control = document.getElementById("slot" + slot);
    const selected = device.manual[String(slot)] || AUTO;
    control.replaceChildren();
    control.appendChild(option(AUTO, "Automatisch", selected === AUTO));
    control.appendChild(option(EMPTY, "Nicht belegt", selected === EMPTY));

    const serials = device.detected.map((item) => item.serial);
    if (selected !== AUTO && selected !== EMPTY && !serials.includes(selected)) {
      control.appendChild(option(selected, selected + " (nicht erkannt)", true));
    }
    for (const serial of serials) {
      control.appendChild(option(serial, serial, selected === serial));
    }
    control.disabled = false;

    const automatic = device.automatic[String(slot)];
    document.getElementById("auto" + slot).textContent =
      automatic ? "Automatisch: " + automatic : "Automatisch: noch nicht zugeordnet";
  }
}

async function loadState() {
  const message = document.getElementById("message");
  message.hidden = true;
  const response = await fetch(apiUrl("api/state"), {cache: "no-store"});
  if (!response.ok) throw new Error("Status konnte nicht geladen werden");
  const previous = document.getElementById("device").value;
  state = await response.json();

  const deviceSelect = document.getElementById("device");
  deviceSelect.replaceChildren();
  if (!state.devices.length) {
    deviceSelect.appendChild(option("", "Noch keine Batterie erkannt", true));
    deviceSelect.disabled = true;
  } else {
    deviceSelect.disabled = false;
    for (const device of state.devices) {
      deviceSelect.appendChild(
        option(device.device_id, device.device_id, device.device_id === previous)
      );
    }
    if (!deviceSelect.value) deviceSelect.selectedIndex = 0;
  }

  document.getElementById("feature-warning").hidden = state.keep_battery_position;
  renderAssignments();
}

function validateUnique() {
  const chosen = [2, 3, 4]
    .map((slot) => document.getElementById("slot" + slot).value)
    .filter((value) => value !== AUTO && value !== EMPTY);
  return new Set(chosen).size === chosen.length;
}

async function saveAssignments() {
  const device = currentDevice();
  if (!device) return;
  const message = document.getElementById("message");
  if (!validateUnique()) {
    message.textContent = "Eine Seriennummer kann nur einer Position zugeordnet werden.";
    message.className = "status error";
    message.hidden = false;
    return;
  }

  const assignments = {};
  for (const slot of [2, 3, 4]) {
    assignments[String(slot)] = document.getElementById("slot" + slot).value;
  }

  const response = await fetch(apiUrl("api/assignments"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({device_id: device.device_id, assignments})
  });
  const result = await response.json();
  if (!response.ok) {
    message.textContent = result.error || "Speichern fehlgeschlagen";
    message.className = "status error";
    message.hidden = false;
    return;
  }

  message.textContent = "Zuordnung gespeichert. Rückkehr zur Add-on-Hauptansicht…";
  message.className = "status ok";
  message.hidden = false;
  setTimeout(goBackToAddon, 900);
}

document.getElementById("device").addEventListener("change", renderAssignments);
document.getElementById("refresh").addEventListener("click", () => loadState().catch(showError));
document.getElementById("save").addEventListener("click", () => saveAssignments().catch(showError));
document.getElementById("back-top").addEventListener("click", goBackToAddon);
document.getElementById("back-bottom").addEventListener("click", goBackToAddon);

function showError(error) {
  const message = document.getElementById("message");
  message.textContent = error.message || String(error);
  message.className = "status error";
  message.hidden = false;
}

loadState().catch(showError);
</script>
</body>
</html>
"""


class BatteryIngressHandler(BaseHTTPRequestHandler):
    server_version = "BetterGroBroIngress/1.0"

    def log_message(self, format, *args):  # noqa: A002
        LOG.debug("Ingress: " + format, *args)

    def _allowed(self) -> bool:
        return self.client_address[0] in _ALLOWED_CLIENTS

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self) -> None:
        body = _INDEX_HTML.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _reject_untrusted_client(self) -> bool:
        if self._allowed():
            return False
        LOG.warning("Rejected non-Ingress web request from %s", self.client_address[0])
        self.send_error(HTTPStatus.FORBIDDEN)
        return True

    def do_GET(self) -> None:  # noqa: N802
        if self._reject_untrusted_client():
            return
        path = urlsplit(self.path).path.rstrip("/")
        if path.endswith("/api/state"):
            self._send_json(load_battery_ui_state())
            return
        if path in {"", "/"} or "/api/hassio_ingress/" in path:
            self._send_html()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if self._reject_untrusted_client():
            return
        path = urlsplit(self.path).path.rstrip("/")
        if not path.endswith("/api/assignments"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Ungültige Anfrage"}, HTTPStatus.BAD_REQUEST)
            return
        if content_length <= 0 or content_length > 65536:
            self._send_json({"error": "Ungültige Anfragegröße"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
            device_id = str(payload["device_id"]).strip()
            assignments = payload["assignments"]
            if not device_id or not isinstance(assignments, dict):
                raise ValueError
            for slot in ("2", "3", "4"):
                value = assignments.get(slot, AUTO_ASSIGNMENT)
                if value not in {AUTO_ASSIGNMENT, EMPTY_ASSIGNMENT} and not _is_plausible_serial(str(value)):
                    raise ValueError
            save_manual_assignments(device_id, assignments)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._send_json(
                {"error": "Ungültige Batterie-Zuordnung"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._send_json({"ok": True})


def start_battery_ingress_server(port: int = INGRESS_PORT) -> ThreadingHTTPServer:
    """Start the local Ingress HTTP service in a daemon thread."""
    import threading

    server = ThreadingHTTPServer(("0.0.0.0", port), BatteryIngressHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="battery-ingress",
        daemon=True,
    )
    thread.start()
    LOG.info("Battery assignment Ingress UI listening on port %d", port)
    return server
