"""Small Home Assistant Ingress UI for Better GroBro battery assignment."""

from __future__ import annotations

import json
import logging
import os
from http import HTTPStatus
import threading
import time

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from grobro.ha.battery_position import (
    AUTO_ASSIGNMENT,
    EMPTY_ASSIGNMENT,
    _is_plausible_serial,
    load_battery_ui_state,
    save_manual_assignments,
)
from grobro.ha.device_inventory import get_device_inventory
from grobro.ha.supervisor_config import (
    SupervisorConfigError,
    get_addon_options,
    get_current_process_logs,
    save_addon_options,
    schedule_restart,
)

LOG = logging.getLogger(__name__)
INGRESS_PORT = int(os.getenv("INGRESS_PORT", "8099"))
_ALLOWED_CLIENTS = {"172.30.32.2", "127.0.0.1", "::1"}

_INDEX_HTML = r"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Better GroBro</title>
  <style>
    :root {
      color-scheme: dark;
      --bg:#07111b; --bg-soft:#0b1724; --panel:#0f1d2b; --panel-2:#122334;
      --panel-3:#172b3e; --border:#24425a; --border-soft:#19344a;
      --text:#f4f8fb; --muted:#91a8ba; --accent:#18b7ff; --accent-2:#0a8fd8;
      --danger:#ff6b76; --ok:#45d483; --warning:#e4aa3d;
      --shadow:0 18px 50px rgba(0,0,0,.28);
    }
    * { box-sizing:border-box; }
    html,body { min-height:100%; }
    body {
      margin:0; padding:12px;
      font:13px/1.4 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      background:
        radial-gradient(circle at 88% 10%,rgba(24,183,255,.08),transparent 30%),
        linear-gradient(180deg,#06101a 0%,#07121c 100%);
      color:var(--text);
    }
    body::before {
      content:"";
      position:fixed; inset:0; pointer-events:none; opacity:.38;
      background:
        linear-gradient(120deg,transparent 0 42%,rgba(24,183,255,.025) 42% 43%,transparent 43% 100%);
    }
    main {
      width:min(1180px,100%);
      min-height:640px;
      margin:0 auto;
      padding:0;
      display:grid;
      grid-template-columns:180px minmax(0,1fr);
      grid-template-rows:52px minmax(0,1fr);
      gap:0;
      overflow:hidden;
      border:1px solid #24455e;
      border-radius:13px;
      background:#07131e;
      box-shadow:0 20px 55px rgba(0,0,0,.28);
    }
    h1 { margin:0; font-size:15px; letter-spacing:-.01em; }
    h2 { margin:0 0 16px; font-size:18px; letter-spacing:-.01em; }
    h3 { margin:18px 0 10px; font-size:15px; }
    p { margin:0; }
    .muted { color:var(--muted); }

    .header {
      grid-column:1/-1; grid-row:1;
      display:flex; justify-content:space-between; align-items:center; gap:12px;
      min-height:52px;
      padding:7px 10px 7px 12px;
      background:linear-gradient(180deg,#102234,#0c1b29);
      border:0; border-bottom:1px solid #19374d;
      border-radius:0; box-shadow:none;
    }
    .header > div:first-child { position:relative; padding-left:0; }
    .header .muted { margin-top:1px; font-size:9px; }

    .tabs {
      grid-column:1; grid-row:2;
      align-self:stretch;
      position:static;
      display:flex; flex-direction:column; gap:5px;
      margin:0; padding:9px 8px;
      background:linear-gradient(180deg,#0d1c2a,#091722);
      border:0; border-right:1px solid #19374d;
      border-radius:0; box-shadow:none;
      min-height:100%;
    }
    .tabs button {
      position:relative;
      width:100%; min-width:0; min-height:34px;
      text-align:left; padding:7px 9px 7px 34px;
      border-radius:7px; border:1px solid transparent;
      background:transparent; color:#bdd0df;
      font-weight:600; cursor:pointer;
      transition:background .15s ease,border-color .15s ease,color .15s ease,transform .15s ease;
    }
    .tabs button:hover { background:#13283a; color:#fff; transform:translateX(1px); }
    .tabs button.active {
      color:#eafdff;
      background:linear-gradient(90deg,rgba(24,183,255,.22),rgba(24,183,255,.09));
      border-color:rgba(24,183,255,.34);
      box-shadow:0 0 0 1px rgba(24,183,255,.06) inset;
    }
    .tabs button::before {
      position:absolute; left:13px; top:50%; transform:translateY(-50%);
      width:16px; text-align:center; color:#7fb4d6; font-size:12px;
    }
    .tabs button.active::before { color:#29c3ff; }
    .tabs button[data-tab="overview"]::before { content:"⌂"; }
    .tabs button[data-tab="batteries"]::before { content:"▣"; }
    .tabs button[data-tab="ha"]::before { content:"◈"; }
    .tabs button[data-tab="mqtt"]::before { content:"⌁"; }
    .tabs button[data-tab="cloud"]::before { content:"☁"; }
    .tabs button[data-tab="diagnostics"]::before { content:"⚙"; }
    .tabs button[data-tab="logs"]::before { content:"≡"; }

    .tab, #config-message { grid-column:2; grid-row:2; min-width:0; padding:10px 12px 12px; }
    .tab { display:none; align-self:start; }
    .tab.active { display:block; }

    .card {
      position:relative; overflow:hidden;
      background:linear-gradient(180deg,rgba(18,35,52,.96),rgba(13,28,42,.96));
      border:1px solid var(--border-soft);
      border-radius:14px; padding:20px; margin-top:14px;
      box-shadow:0 12px 34px rgba(0,0,0,.18);
    }
    .card::after {
      content:""; position:absolute; inset:0 0 auto 0; height:1px;
      background:linear-gradient(90deg,transparent,rgba(91,205,255,.28),transparent);
      pointer-events:none;
    }

    .summary {
      display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px;
      margin-bottom:2px;
    }
    .metric {
      min-height:96px;
      background:linear-gradient(180deg,#11263a,#0d2031);
      border:1px solid var(--border-soft);
      border-radius:12px; padding:15px 16px;
      box-shadow:0 10px 25px rgba(0,0,0,.14);
    }
    .metric > span:first-child { text-transform:uppercase; letter-spacing:.07em; font-size:10px; font-weight:700; }
    .metric strong { display:block; font-size:21px; margin-top:8px; letter-spacing:-.02em; }
    #summary-state { color:var(--ok); }
    #summary-devices { margin-top:9px; }

    .header-title-row { display:flex; align-items:center; gap:8px; }
    .header-right { display:flex; align-items:center; gap:8px; }
    .compact-back { width:32px; min-width:32px; min-height:30px; padding:4px; font-size:15px; }
    .dashboard-panel {
      margin-top:10px; padding:12px;
      border:1px solid #19384f; border-radius:12px;
      background:linear-gradient(180deg,#0e1d2b 0%,#0b1825 100%);
      box-shadow:0 12px 28px rgba(0,0,0,.16);
    }
    #tab-overview > .dashboard-panel:first-child { margin-top:0; }
    .dashboard-section-title {
      display:flex; align-items:flex-start; justify-content:space-between; gap:12px;
      margin-bottom:9px;
    }
    .dashboard-section-title h3 { margin:0 0 2px; font-size:14px; }
    .dashboard-section-title p { font-size:11px; }

    .device-cards {
      display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; align-items:stretch;
      grid-auto-rows:88px;
    }
    .device-card {
      min-width:0; display:grid;
      grid-template-columns:48px minmax(0,1fr) 72px;
      gap:12px; align-items:center;
      min-height:88px; height:88px; padding:10px 12px;
      border:1px solid #1e4058; border-radius:10px;
      background:linear-gradient(180deg,#112537,#0d1d2b);
    }
    .device-icon {
      width:44px; height:44px; display:grid; place-items:center;
      border-radius:7px; border:1px solid #bdc9d1;
      background:linear-gradient(145deg,#f7f9fa,#cbd3d8);
      color:#142832; font-weight:950; font-size:12px; line-height:1; letter-spacing:-.02em; white-space:nowrap; overflow:hidden;
      box-shadow:0 7px 14px rgba(0,0,0,.22);
    }
    .device-card strong { display:block; font-size:17px; line-height:1.05; }
    .device-serial {
      margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      color:#9ab0c0; font:12px/1.35 ui-monospace,SFMono-Regular,Consolas,monospace;
    }
    .online-line { display:flex; align-items:center; gap:6px; margin-top:8px; color:#9ed3b1; font-size:12px; }
    .online-line::before { content:""; width:6px; height:6px; border-radius:50%; background:var(--ok); }
    .wifi-box {
      min-width:72px; width:72px; text-align:right; color:#afc2cf; font-size:11px;
    }
    .wifi-bars {
      height:20px; display:flex; justify-content:flex-end; align-items:flex-end; gap:2px; margin-bottom:2px;
    }
    .wifi-bars span {
      display:block; width:3px; border-radius:2px 2px 0 0; background:#385366;
    }
    .wifi-bars span:nth-child(1){height:5px}.wifi-bars span:nth-child(2){height:9px}
    .wifi-bars span:nth-child(3){height:13px}.wifi-bars span:nth-child(4){height:17px}
    .wifi-bars span.on { background:#58d897; box-shadow:0 0 6px rgba(88,216,151,.20); }
    .wifi-value { white-space:nowrap; }

    .battery-cards { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; align-items:stretch; grid-auto-rows:88px; }
    .battery-card {
      display:grid; grid-template-columns:48px minmax(0,1fr) 72px;
      gap:10px; align-items:center;
      min-height:88px; height:88px; padding:10px 12px;
      border:1px solid #1d3e55; border-radius:10px;
      background:linear-gradient(180deg,#102437,#0c1c2a);
    }
    .battery-icon {
      position:relative; width:26px; height:44px; margin:auto;
      border:2px solid #6f8b9e; border-radius:4px; background:#07121b; overflow:hidden;
    }
    .battery-icon::before { content:""; position:absolute; width:10px; height:4px; left:6px; top:-6px; border-radius:2px 2px 0 0; background:#6f8b9e; }
    .battery-fill {
      position:absolute; left:3px; right:3px; bottom:3px; max-height:calc(100% - 6px);
      border-radius:2px; background:linear-gradient(180deg,#77e49e,#33bd70);
      transition:height .25s ease;
    }
    .battery-card strong { display:block; font-size:17px; line-height:1.05; }
    .battery-card .muted { font-size:12px; line-height:1.35; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .battery-assignment { margin-top:3px; color:#68cf91; font-size:12px; line-height:1.2; }
    .battery-value { min-width:72px; text-align:right; font-size:19px; line-height:1.05; font-weight:800; color:#e8f7ed; }
    .battery-value small { display:block; margin-top:4px; font-size:11px; line-height:1.2; color:#9ab0c0; font-weight:650; }

    .overview-log {
      margin:0; height:150px; min-height:150px; max-height:150px; overflow:auto;
      white-space:pre; background:#050c12; border:1px solid #17364c; border-radius:9px;
      padding:11px 12px; color:#b8d2e2;
      font:10px/1.45 ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;
    }
    .overview-empty {
      grid-column:1/-1; padding:18px; border:1px dashed #28485d; border-radius:9px;
      color:var(--muted); text-align:center; background:#091722;
    }

    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px 18px; }
    .field { min-width:0; }
    .field.full { grid-column:1/-1; }
    label { display:block; font-weight:650; margin-bottom:6px; color:#e7f0f7; }
    .help { color:var(--muted); font-size:12px; margin-top:5px; }

    input, select, button {
      min-height:42px; border-radius:9px; border:1px solid var(--border);
      background:#0a1825; color:var(--text); padding:8px 11px; font:inherit;
    }
    input,select { width:100%; outline:none; transition:border-color .15s ease,box-shadow .15s ease,background .15s ease; }
    input:focus,select:focus {
      border-color:var(--accent);
      box-shadow:0 0 0 3px rgba(24,183,255,.12);
      background:#0c1c2a;
    }
    input[type="checkbox"] {
      width:auto; min-height:auto; transform:scale(1.12); margin-right:9px;
      accent-color:var(--accent);
    }
    .check { display:flex; align-items:center; min-height:42px; color:#c6d5e0; }

    button {
      cursor:pointer;
      background:linear-gradient(180deg,#26c4ff,#08a5e7);
      color:#032034; border-color:transparent; font-weight:750;
      box-shadow:0 6px 18px rgba(0,154,222,.15);
    }
    button.secondary {
      background:#142535; color:#dce8f1; border-color:#29475f; box-shadow:none;
    }
    button:disabled { opacity:.5; cursor:default; }

    .actions { display:flex; justify-content:flex-end; gap:10px; flex-wrap:wrap; margin-top:18px; }
    .status {
      margin-top:14px; border-radius:10px; padding:11px 13px;
      border:1px solid var(--border); background:#0c1b29;
    }
    .status.ok { border-color:rgba(69,212,131,.6); }
    .status.error { border-color:rgba(255,107,118,.65); color:#ffd6da; background:#27161b; }
    .status.warning { border-color:rgba(228,170,61,.65); background:#2a2417; }

    .serials { display:flex; gap:7px; flex-wrap:wrap; margin-top:10px; }
    .chip {
      display:inline-flex; align-items:center; min-height:28px;
      border:1px solid #2a4a62; border-radius:999px;
      padding:5px 10px; color:#c9dce9; background:#0d2131;
      font-size:12px;
    }
    .chip::before {
      content:""; width:7px; height:7px; margin-right:7px; border-radius:50%;
      background:var(--ok); box-shadow:0 0 0 3px rgba(69,212,131,.11);
    }

    .battery-row {
      display:grid; grid-template-columns:minmax(180px,1fr) minmax(280px,1.4fr);
      gap:18px; align-items:center; padding:14px 0; border-top:1px solid var(--border-soft);
    }
    [hidden] { display:none !important; }
    .battery-row:first-of-type { border-top:0; }

    .section-note { margin-top:12px; color:var(--muted); font-size:12px; }
    .log-toolbar {
      display:flex; justify-content:space-between; align-items:center;
      gap:12px; flex-wrap:wrap; margin-bottom:12px;
    }
    .log-output {
      margin:0; height:420px; min-height:420px; max-height:420px;
      overflow-y:auto; overflow-x:auto; overscroll-behavior:contain;
      scrollbar-gutter:stable; touch-action:pan-y; -webkit-overflow-scrolling:touch;
      -webkit-text-size-adjust:100%; text-size-adjust:100%;
      white-space:pre; word-break:normal;
      background:#050d14; border:1px solid #1d3a50; border-radius:10px;
      padding:15px; font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;
      color:#cce3f1;
      box-shadow:inset 0 0 0 1px rgba(255,255,255,.015);
    }

    @media (max-width:900px) {
      main { grid-template-columns:180px minmax(0,1fr); gap:14px; padding:14px; }
      .summary { grid-template-columns:1fr; }
      .metric { min-height:auto; }
      .device-cards { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .battery-cards { grid-template-columns:repeat(2,minmax(0,1fr)); }
    }
    @media (max-width:700px) {
      body { padding:0; }
      main { display:block; min-height:100vh; border:0; border-radius:0; }
      .header { position:sticky; top:0; z-index:5; margin-bottom:0; border-radius:0; }
      .header #back-top { min-width:44px; }
      .tabs {
        position:sticky; top:52px; z-index:4;
        flex-direction:row; overflow-x:auto; gap:6px; padding:7px; margin-bottom:0;
        border-right:0; border-bottom:1px solid #19374d;
        scrollbar-width:none;
      }
      .tabs::-webkit-scrollbar { display:none; }
      .tabs button { width:auto; flex:0 0 auto; padding-left:36px; }
      .grid,.battery-row,.device-cards,.battery-cards { grid-template-columns:1fr; }
      .dashboard-head,.dashboard-section-title { flex-direction:column; align-items:stretch; }
      .dashboard-state { align-self:flex-start; }
      .actions button,.header button { width:100%; }
      .header { align-items:stretch; }
      .header > div:first-child { align-self:center; }
      .card { padding:16px; border-radius:12px; }
    }
  </style>
</head>
<body>
<main>
  <div class="header">
    <div>
      <div class="header-title-row">
        <h1>Better GroBro</h1>
        <span id="dashboard-version" class="version-pill">–</span>
      </div>
      <p class="muted">Konfiguration und Batterie-Zuordnung</p>
    </div>
    <div class="header-right">
      <div class="dashboard-state">
        <span id="overview-status-dot" class="status-dot"></span>
        <span id="overview-status-text">–</span>
      </div>
      <button id="back-top" type="button" class="secondary compact-back" aria-label="Zurück zum Add-on" title="Zurück zum Add-on">↩</button>
    </div>
  </div>

  <nav class="tabs">
    <button type="button" class="secondary active" data-tab="overview">Übersicht</button>
    <button type="button" class="secondary" data-tab="batteries">Batterien</button>
    <button type="button" class="secondary" data-tab="ha">Home Assistant</button>
    <button type="button" class="secondary" data-tab="mqtt">MQTT</button>
    <button type="button" class="secondary" data-tab="cloud">Growatt Cloud</button>
    <button type="button" class="secondary" data-tab="diagnostics">Diagnose</button>
    <button type="button" class="secondary" data-tab="logs">Protokoll</button>
  </nav>

  <section id="tab-overview" class="tab active">
    <div class="dashboard-panel">
      <div class="dashboard-section-title">
        <div>
          <h3>Geräte</h3>
          <p class="muted">Live erkannte Growatt-Geräte</p>
        </div>
        <span id="summary-device-count" class="count-pill">0</span>
      </div>
      <div id="overview-device-cards" class="device-cards">
        <div class="overview-empty">Noch keine Live-Telemetrie.</div>
      </div>
      <div id="summary-devices" class="serials" hidden></div>
      <strong id="summary-version" hidden>–</strong>
      <strong id="summary-state" hidden>–</strong>
    </div>

    <div class="dashboard-panel">
      <div class="dashboard-section-title">
        <div>
          <h3>Batterien</h3>
          <p class="muted">Bat1 ist der NOAH Master, Bat2–Bat4 erscheinen je nach vorhandener Batterie.</p>
        </div>
      </div>
      <div id="overview-battery-cards" class="battery-cards">
        <div class="overview-empty">Noch keine Batterie erkannt.</div>
      </div>
    </div>

    <div class="dashboard-panel">
      <div class="dashboard-section-title">
        <div>
          <h3>Aktuelle Sitzung</h3>
          <p class="muted">Letzte Better-GroBro-Protokolleinträge</p>
        </div>
      </div>
      <pre id="overview-log-output" class="overview-log">Protokoll wird geladen…</pre>
    </div>
  </section>

  <section id="tab-batteries" class="tab">
    <div class="card">
      <h2>Batterie-Einstellungen</h2>
      <div class="grid">
        <div class="field"><label>Stabile Batteriepositionen</label><div class="check"><input id="cfg-KEEP_BATTERY_POSITION" type="checkbox">NOAH/NEXA per Seriennummer stabil halten</div></div>
        <div class="field"><label for="cfg-MAX_BAT">Maximale Batterieanzahl</label><select id="cfg-MAX_BAT"><option value="auto">Automatisch</option><option>1</option><option>2</option><option>3</option><option>4</option></select></div>
      </div>
      <div class="actions config-actions"></div>
    </div>
    <div class="card">
      <h2>Batterie-Zuordnung</h2>
      <div class="grid">
        <div class="field full">
          <label for="device">Bat1 (Master)</label>
          <select id="device"></select>
        </div>
      </div>
      <div id="detected" class="serials"></div>
      <div id="row-slot2" class="battery-row"><div><label for="slot2">Bat2</label><div id="auto2" class="muted"></div></div><select id="slot2"></select></div>
      <div id="row-slot3" class="battery-row"><div><label for="slot3">Bat3</label><div id="auto3" class="muted"></div></div><select id="slot3"></select></div>
      <div id="row-slot4" class="battery-row"><div><label for="slot4">Bat4</label><div id="auto4" class="muted"></div></div><select id="slot4"></select></div>
      <div class="actions"><button id="battery-save" type="button">Batterie-Zuordnung speichern</button></div>
      <div id="battery-message" class="status" hidden></div>
    </div>
  </section>

  <section id="tab-ha" class="tab">
    <div class="card">
      <h2>Home Assistant</h2>
      <div class="grid">
        <div class="field"><label for="cfg-MAX_SLOTS">Zeitfenster</label><select id="cfg-MAX_SLOTS"><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option><option>6</option><option>7</option><option>8</option><option>9</option></select><div class="help">Anzahl der Batterie-Zeitfenster in Home Assistant.</div></div>
        <div class="field"><label for="cfg-DEVICE_TIMEOUT">Geräte-Timeout (Sekunden)</label><input id="cfg-DEVICE_TIMEOUT" type="number" min="1" step="1"><div class="help">Nach dieser Zeit ohne Telemetrie werden die Entities unavailable, bleiben aber in Home Assistant erhalten.</div></div>
        <div class="field"><label>Availability-Sensor</label><div class="check"><input id="cfg-AVAILABILITY_SENSOR" type="checkbox">Zusätzlichen Online-Sensor erzeugen</div></div>
        <div class="field"><label for="cfg-HA_BASE_TOPIC">HA Basis-Topic</label><input id="cfg-HA_BASE_TOPIC" type="text"></div>
        <div class="field"><label for="cfg-MQTT_CLIENT_SUFFIX">MQTT Client-Suffix</label><input id="cfg-MQTT_CLIENT_SUFFIX" type="text"></div>
        <div class="field"><label for="cfg-TZ">Zeitzone</label><input id="cfg-TZ" type="text" placeholder="leer = Home Assistant übernehmen"></div>
      </div>
      <div class="actions config-actions"></div>
    </div>
  </section>

  <section id="tab-mqtt" class="tab">
    <div class="card">
      <h2>Growatt / Quell-MQTT</h2>
      <div class="grid">
        <div class="field"><label for="cfg-SOURCE_MQTT_HOST">Host</label><input id="cfg-SOURCE_MQTT_HOST" type="text"></div>
        <div class="field"><label for="cfg-SOURCE_MQTT_PORT">Port</label><input id="cfg-SOURCE_MQTT_PORT" type="number" min="1" max="65535"></div>
        <div class="field"><label for="cfg-SOURCE_MQTT_USER">Benutzername</label><input id="cfg-SOURCE_MQTT_USER" type="text"></div>
        <div class="field"><label for="cfg-SOURCE_MQTT_PASS">Passwort</label><input id="cfg-SOURCE_MQTT_PASS" type="password"></div>
        <div class="field"><label>TLS</label><div class="check"><input id="cfg-SOURCE_MQTT_TLS" type="checkbox">TLS aktivieren</div></div>
      </div>
    </div>
    <div class="card">
      <h2>Home Assistant / Ziel-MQTT</h2>
      <div class="grid">
        <div class="field"><label for="cfg-TARGET_MQTT_HOST">Host</label><input id="cfg-TARGET_MQTT_HOST" type="text"></div>
        <div class="field"><label for="cfg-TARGET_MQTT_PORT">Port</label><input id="cfg-TARGET_MQTT_PORT" type="number" min="1" max="65535"></div>
        <div class="field"><label for="cfg-TARGET_MQTT_USER">Benutzername</label><input id="cfg-TARGET_MQTT_USER" type="text"></div>
        <div class="field"><label for="cfg-TARGET_MQTT_PASS">Passwort</label><input id="cfg-TARGET_MQTT_PASS" type="password"></div>
        <div class="field"><label>TLS</label><div class="check"><input id="cfg-TARGET_MQTT_TLS" type="checkbox">TLS aktivieren</div></div>
      </div>
      <div class="actions config-actions"></div>
    </div>
  </section>

  <section id="tab-cloud" class="tab">
    <div class="card">
      <h2>Growatt Cloud</h2>
      <div class="grid">
        <div class="field"><label>Cloud-Weiterleitung</label><div class="check"><input id="cfg-GROWATT_CLOUD" type="checkbox">Nachrichten zur/von der Growatt Cloud weiterleiten</div></div>
        <div class="field"><label>Konfigurationsfilter</label><div class="check"><input id="cfg-GROWATT_CLOUD_CONFIG_FILTER" type="checkbox">Ferninitiierte Konfigurationsnachrichten blockieren</div></div>
      </div>
      <div class="actions config-actions"></div>
    </div>
  </section>

  <section id="tab-diagnostics" class="tab">
    <div class="card">
      <h2>Diagnose</h2>
      <div class="grid">
        <div class="field"><label for="cfg-LOG_LEVEL">Log-Level</label><select id="cfg-LOG_LEVEL"><option>ERROR</option><option>INFO</option><option>DEBUG</option></select></div>
        <div class="field"><label>Roh-Nachrichten speichern</label><div class="check"><input id="cfg-DUMP_MESSAGES" type="checkbox">Raw MQTT Dump aktivieren</div></div>
        <div class="field full"><label for="cfg-DUMP_DIR">Dump-Verzeichnis</label><input id="cfg-DUMP_DIR" type="text"></div>
        <div class="field"><label>Register-Debug</label><div class="check"><input id="cfg-REGISTER_DEBUG" type="checkbox">Passiven Register-Debugger aktivieren</div></div>
        <div class="field"><label>Nur Änderungen</label><div class="check"><input id="cfg-REGISTER_DEBUG_CHANGES_ONLY" type="checkbox">Nach Erstwert nur Änderungen protokollieren</div></div>
        <div class="field"><label for="cfg-REGISTER_DEBUG_MAX_REGISTER">Maximales Register</label><input id="cfg-REGISTER_DEBUG_MAX_REGISTER" type="number" min="0" max="65535"></div>
        <div class="field"><label for="cfg-REGISTER_DEBUG_DIR">Register-Debug-Verzeichnis</label><input id="cfg-REGISTER_DEBUG_DIR" type="text"></div>
      </div>
      <div class="actions config-actions"></div>
    </div>
  </section>

  <section id="tab-logs" class="tab">
    <div class="card">
      <div class="log-toolbar">
        <div>
          <h2>Protokoll</h2>
          <div class="muted"><span>Seit Better-GroBro-Start:</span> <span id="log-started">–</span></div>
        </div>
        <button id="log-refresh" type="button" class="secondary">Aktualisieren</button>
      </div>
      <p class="section-note">Es werden nur Einträge des aktuell laufenden Better-GroBro-Prozesses angezeigt. Ältere Supervisor-Protokolle bleiben ausgeblendet.</p>
      <pre id="log-output" class="log-output">Protokoll wird geladen…</pre>
    </div>
  </section>

  <div id="config-message" class="status" hidden></div>
</main>

<script>
const AUTO="__auto__", EMPTY="__empty__";
let batteryState=null, configState=null, configBaseline=null, currentLang="de", logTimer=null, logFollowTail=true, logLastText=null;
const TEXTS={
  en:{
    "Konfiguration und Batterie-Zuordnung":"Configuration and battery assignment","Zurück zum Add-on":"Back to add-on",
    "Übersicht":"Overview","Batterien":"Batteries","Diagnose":"Diagnostics","Protokoll":"Log","Version":"Version","Add-on Status":"Add-on status",
    "Erkannte Geräte":"Detected devices","Empfohlene Konfiguration":"Recommended configuration",
    "Verwende bevorzugt diese Better-GroBro-Oberfläche. Sie bearbeitet direkt die offiziellen Home-Assistant-Add-on-Optionen; der native Konfiguration-Tab bleibt als Fallback verfügbar und verwendet dieselben Werte.":"Prefer this Better GroBro interface. It edits the official Home Assistant add-on options directly; the native Configuration tab remains available as a fallback and uses the same values.",
    "Änderungen an Better-GroBro-Optionen werden beim Start geladen. Verwende daher nach Änderungen vorzugsweise":"Changes to Better GroBro options are loaded at startup. After changing options, preferably use",
    "Speichern & Better GroBro neu starten":"Save & restart Better GroBro","Batterie-Einstellungen":"Battery settings","Batterie-Zuordnung":"Battery assignment","Bat1 (Master)":"Bat1 (Master)",
    "Zurück":"Back","Batterie-Zuordnung speichern":"Save battery assignment","Stabile Batteriepositionen":"Stable battery positions",
    "NOAH/NEXA per Seriennummer stabil halten":"Keep NOAH/NEXA stable by serial number","Maximale Batterieanzahl":"Maximum battery count",
    "Automatisch":"Automatic","Zeitfenster":"Time slots","Anzahl der Batterie-Zeitfenster in Home Assistant.":"Number of battery scheduling slots in Home Assistant.",
    "Geräte-Timeout (Sekunden)":"Device timeout (seconds)","Nach dieser Zeit ohne Telemetrie werden die Entities unavailable, bleiben aber in Home Assistant erhalten.":"After this time without telemetry, entities become unavailable but remain in Home Assistant.",
    "Availability-Sensor":"Availability sensor","Zusätzlichen Online-Sensor erzeugen":"Create an additional online sensor",
    
    "HA Basis-Topic":"HA base topic","MQTT Client-Suffix":"MQTT client suffix","Zeitzone":"Timezone",
    "Growatt / Quell-MQTT":"Growatt / source MQTT","Host":"Host","Port":"Port","Benutzername":"Username","Passwort":"Password",
    "TLS aktivieren":"Enable TLS","Home Assistant / Ziel-MQTT":"Home Assistant / target MQTT","Cloud-Weiterleitung":"Cloud forwarding",
    "Nachrichten zur/von der Growatt Cloud weiterleiten":"Forward messages to/from Growatt Cloud","Konfigurationsfilter":"Configuration filter",
    "Ferninitiierte Konfigurationsnachrichten blockieren":"Block remotely initiated configuration messages","Log-Level":"Log level",
    "Roh-Nachrichten speichern":"Store raw messages","Raw MQTT Dump aktivieren":"Enable raw MQTT dump","Dump-Verzeichnis":"Dump directory",
    "Register-Debug":"Register debug","Passiven Register-Debugger aktivieren":"Enable passive register debugger","Nur Änderungen":"Changes only",
    "Nach Erstwert nur Änderungen protokollieren":"After first value, log changes only","Maximales Register":"Maximum register",
    "Register-Debug-Verzeichnis":"Register debug directory","Nicht belegt":"Not occupied",
    "Noch keine Batterie erkannt":"No battery detected yet","Seit Better-GroBro-Start:":"Since Better GroBro start:","Aktualisieren":"Refresh","Es werden nur Einträge des aktuell laufenden Better-GroBro-Prozesses angezeigt. Ältere Supervisor-Protokolle bleiben ausgeblendet.":"Only entries from the currently running Better GroBro process are shown. Older Supervisor logs remain hidden.","Protokoll wird geladen…":"Loading log…"
  },
  fr:{
    "Konfiguration und Batterie-Zuordnung":"Configuration et affectation des batteries","Zurück zum Add-on":"Retour à l'add-on",
    "Übersicht":"Vue d'ensemble","Batterien":"Batteries","Diagnose":"Diagnostic","Protokoll":"Journal","Version":"Version","Add-on Status":"État de l'add-on",
    "Erkannte Geräte":"Appareils détectés","Empfohlene Konfiguration":"Configuration recommandée",
    "Verwende bevorzugt diese Better-GroBro-Oberfläche. Sie bearbeitet direkt die offiziellen Home-Assistant-Add-on-Optionen; der native Konfiguration-Tab bleibt als Fallback verfügbar und verwendet dieselben Werte.":"Utilisez de préférence cette interface Better GroBro. Elle modifie directement les options officielles de l'add-on Home Assistant ; l'onglet Configuration natif reste disponible comme solution de secours et utilise les mêmes valeurs.",
    "Änderungen an Better-GroBro-Optionen werden beim Start geladen. Verwende daher nach Änderungen vorzugsweise":"Les modifications des options Better GroBro sont chargées au démarrage. Après une modification, utilisez de préférence",
    "Speichern & Better GroBro neu starten":"Enregistrer et redémarrer Better GroBro","Batterie-Einstellungen":"Paramètres de batterie","Batterie-Zuordnung":"Affectation des batteries","Bat1 (Master)":"Bat1 (Master)",
    "Zurück":"Retour","Batterie-Zuordnung speichern":"Enregistrer l'affectation","Stabile Batteriepositionen":"Positions de batterie stables",
    "NOAH/NEXA per Seriennummer stabil halten":"Maintenir NOAH/NEXA stables par numéro de série","Maximale Batterieanzahl":"Nombre maximal de batteries",
    "Automatisch":"Automatique","Zeitfenster":"Créneaux horaires","Anzahl der Batterie-Zeitfenster in Home Assistant.":"Nombre de créneaux de batterie dans Home Assistant.",
    "Geräte-Timeout (Sekunden)":"Délai de l'appareil (secondes)","Nach dieser Zeit ohne Telemetrie werden die Entities unavailable, bleiben aber in Home Assistant erhalten.":"Après ce délai sans télémétrie, les entités deviennent indisponibles mais restent dans Home Assistant.",
    "Availability-Sensor":"Capteur de disponibilité","Zusätzlichen Online-Sensor erzeugen":"Créer un capteur en ligne supplémentaire",
    
    "HA Basis-Topic":"Topic de base HA","MQTT Client-Suffix":"Suffixe client MQTT","Zeitzone":"Fuseau horaire",
    "Growatt / Quell-MQTT":"Growatt / MQTT source","Host":"Hôte","Port":"Port","Benutzername":"Nom d'utilisateur","Passwort":"Mot de passe",
    "TLS aktivieren":"Activer TLS","Home Assistant / Ziel-MQTT":"Home Assistant / MQTT cible","Cloud-Weiterleitung":"Transfert cloud",
    "Nachrichten zur/von der Growatt Cloud weiterleiten":"Transférer les messages vers/depuis Growatt Cloud","Konfigurationsfilter":"Filtre de configuration",
    "Ferninitiierte Konfigurationsnachrichten blockieren":"Bloquer les changements de configuration distants","Log-Level":"Niveau de journal",
    "Roh-Nachrichten speichern":"Enregistrer les messages bruts","Raw MQTT Dump aktivieren":"Activer le dump MQTT brut","Dump-Verzeichnis":"Répertoire du dump",
    "Register-Debug":"Débogage registres","Passiven Register-Debugger aktivieren":"Activer le débogueur passif des registres","Nur Änderungen":"Modifications uniquement",
    "Nach Erstwert nur Änderungen protokollieren":"Après la première valeur, journaliser uniquement les changements","Maximales Register":"Registre maximal",
    "Register-Debug-Verzeichnis":"Répertoire de débogage des registres",
    "Nicht belegt":"Non occupé","Noch keine Batterie erkannt":"Aucune batterie détectée","Seit Better-GroBro-Start:":"Depuis le démarrage de Better GroBro :","Aktualisieren":"Actualiser","Es werden nur Einträge des aktuell laufenden Better-GroBro-Prozesses angezeigt. Ältere Supervisor-Protokolle bleiben ausgeblendet.":"Seules les entrées du processus Better GroBro actuellement en cours sont affichées. Les anciens journaux Supervisor restent masqués.","Protokoll wird geladen…":"Chargement du journal…"
  },
  es:{
    "Konfiguration und Batterie-Zuordnung":"Configuración y asignación de baterías","Zurück zum Add-on":"Volver al complemento",
    "Übersicht":"Resumen","Batterien":"Baterías","Diagnose":"Diagnóstico","Protokoll":"Registro","Version":"Versión","Add-on Status":"Estado del complemento",
    "Erkannte Geräte":"Dispositivos detectados","Empfohlene Konfiguration":"Configuración recomendada",
    "Verwende bevorzugt diese Better-GroBro-Oberfläche. Sie bearbeitet direkt die offiziellen Home-Assistant-Add-on-Optionen; der native Konfiguration-Tab bleibt als Fallback verfügbar und verwendet dieselben Werte.":"Use preferentemente esta interfaz de Better GroBro. Edita directamente las opciones oficiales del complemento de Home Assistant; la pestaña Configuración nativa permanece disponible como respaldo y utiliza los mismos valores.",
    "Änderungen an Better-GroBro-Optionen werden beim Start geladen. Verwende daher nach Änderungen vorzugsweise":"Los cambios de Better GroBro se cargan al iniciar. Después de cambiar opciones, use preferiblemente",
    "Speichern & Better GroBro neu starten":"Guardar y reiniciar Better GroBro","Batterie-Einstellungen":"Ajustes de batería","Batterie-Zuordnung":"Asignación de baterías","Bat1 (Master)":"Bat1 (Master)",
    "Zurück":"Volver","Batterie-Zuordnung speichern":"Guardar asignación","Stabile Batteriepositionen":"Posiciones estables de batería",
    "NOAH/NEXA per Seriennummer stabil halten":"Mantener NOAH/NEXA estables por número de serie","Maximale Batterieanzahl":"Número máximo de baterías",
    "Automatisch":"Automático","Zeitfenster":"Franjas horarias","Anzahl der Batterie-Zeitfenster in Home Assistant.":"Número de franjas de batería en Home Assistant.",
    "Geräte-Timeout (Sekunden)":"Tiempo de espera del dispositivo (segundos)","Nach dieser Zeit ohne Telemetrie werden die Entities unavailable, bleiben aber in Home Assistant erhalten.":"Tras este tiempo sin telemetría, las entidades pasan a no disponibles pero permanecen en Home Assistant.",
    "Availability-Sensor":"Sensor de disponibilidad","Zusätzlichen Online-Sensor erzeugen":"Crear un sensor en línea adicional",
    "HA Basis-Topic":"Topic base de HA","MQTT Client-Suffix":"Sufijo de cliente MQTT","Zeitzone":"Zona horaria",
    "Growatt / Quell-MQTT":"Growatt / MQTT origen","Host":"Host","Port":"Puerto","Benutzername":"Usuario","Passwort":"Contraseña",
    "TLS aktivieren":"Activar TLS","Home Assistant / Ziel-MQTT":"Home Assistant / MQTT destino","Cloud-Weiterleitung":"Reenvío a la nube",
    "Nachrichten zur/von der Growatt Cloud weiterleiten":"Reenviar mensajes hacia/desde Growatt Cloud","Konfigurationsfilter":"Filtro de configuración",
    "Ferninitiierte Konfigurationsnachrichten blockieren":"Bloquear cambios de configuración remotos","Log-Level":"Nivel de registro",
    "Roh-Nachrichten speichern":"Guardar mensajes sin procesar","Raw MQTT Dump aktivieren":"Activar volcado MQTT","Dump-Verzeichnis":"Directorio de volcado",
    "Register-Debug":"Depuración de registros","Passiven Register-Debugger aktivieren":"Activar depurador pasivo de registros","Nur Änderungen":"Solo cambios",
    "Nach Erstwert nur Änderungen protokollieren":"Tras el primer valor, registrar solo cambios","Maximales Register":"Registro máximo",
    "Register-Debug-Verzeichnis":"Directorio de depuración de registros","Nicht belegt":"No ocupado",
    "Noch keine Batterie erkannt":"Aún no se detectó ninguna batería"
  },
  nl:{
    "Konfiguration und Batterie-Zuordnung":"Configuratie en batterijtoewijzing","Zurück zum Add-on":"Terug naar add-on",
    "Übersicht":"Overzicht","Batterien":"Batterijen","Diagnose":"Diagnose","Protokoll":"Logboek","Version":"Versie","Add-on Status":"Add-onstatus",
    "Erkannte Geräte":"Gedetecteerde apparaten","Empfohlene Konfiguration":"Aanbevolen configuratie",
    "Verwende bevorzugt diese Better-GroBro-Oberfläche. Sie bearbeitet direkt die offiziellen Home-Assistant-Add-on-Optionen; der native Konfiguration-Tab bleibt als Fallback verfügbar und verwendet dieselben Werte.":"Gebruik bij voorkeur deze Better GroBro-interface. Deze bewerkt rechtstreeks de officiële Home Assistant add-onopties; het native tabblad Configuratie blijft als fallback beschikbaar en gebruikt dezelfde waarden.",
    "Änderungen an Better-GroBro-Optionen werden beim Start geladen. Verwende daher nach Änderungen vorzugsweise":"Wijzigingen in Better GroBro-opties worden bij het starten geladen. Gebruik daarom na wijzigingen bij voorkeur",
    "Speichern & Better GroBro neu starten":"Opslaan en Better GroBro herstarten","Batterie-Einstellungen":"Batterij-instellingen","Batterie-Zuordnung":"Batterijtoewijzing","Bat1 (Master)":"Bat1 (Master)",
    "Zurück":"Terug","Batterie-Zuordnung speichern":"Batterijtoewijzing opslaan","Stabile Batteriepositionen":"Stabiele batterijposities",
    "NOAH/NEXA per Seriennummer stabil halten":"NOAH/NEXA per serienummer op een vaste positie houden","Maximale Batterieanzahl":"Maximaal aantal batterijen",
    "Automatisch":"Automatisch","Zeitfenster":"Tijdsloten","Anzahl der Batterie-Zeitfenster in Home Assistant.":"Aantal batterij-tijdsloten in Home Assistant.",
    "Geräte-Timeout (Sekunden)":"Apparaattime-out (seconden)","Nach dieser Zeit ohne Telemetrie werden die Entities unavailable, bleiben aber in Home Assistant erhalten.":"Na deze tijd zonder telemetrie worden de entiteiten niet beschikbaar, maar blijven ze in Home Assistant behouden.",
    "Availability-Sensor":"Beschikbaarheidssensor","Zusätzlichen Online-Sensor erzeugen":"Extra online-sensor maken",
    "HA Basis-Topic":"HA-basistopic","MQTT Client-Suffix":"MQTT-clientsuffix","Zeitzone":"Tijdzone",
    "Growatt / Quell-MQTT":"Growatt / bron-MQTT","Host":"Host","Port":"Poort","Benutzername":"Gebruikersnaam","Passwort":"Wachtwoord",
    "TLS aktivieren":"TLS inschakelen","Home Assistant / Ziel-MQTT":"Home Assistant / doel-MQTT","Cloud-Weiterleitung":"Cloud-doorsturen",
    "Nachrichten zur/von der Growatt Cloud weiterleiten":"Berichten naar/van Growatt Cloud doorsturen","Konfigurationsfilter":"Configuratiefilter",
    "Ferninitiierte Konfigurationsnachrichten blockieren":"Op afstand gestarte configuratieberichten blokkeren","Log-Level":"Logniveau",
    "Roh-Nachrichten speichern":"Ruwe berichten opslaan","Raw MQTT Dump aktivieren":"Ruwe MQTT-dump inschakelen","Dump-Verzeichnis":"Dumpmap",
    "Register-Debug":"Registerdebug","Passiven Register-Debugger aktivieren":"Passieve registerdebugger inschakelen","Nur Änderungen":"Alleen wijzigingen",
    "Nach Erstwert nur Änderungen protokollieren":"Na de eerste waarde alleen wijzigingen loggen","Maximales Register":"Maximaal register",
    "Register-Debug-Verzeichnis":"Registerdebugmap","Nicht belegt":"Niet bezet",
    "Noch keine Batterie erkannt":"Nog geen batterij gedetecteerd","Seit Better-GroBro-Start:":"Sinds start van Better GroBro:","Aktualisieren":"Vernieuwen","Es werden nur Einträge des aktuell laufenden Better-GroBro-Prozesses angezeigt. Ältere Supervisor-Protokolle bleiben ausgeblendet.":"Alleen vermeldingen van het huidige Better GroBro-proces worden weergegeven. Oudere Supervisor-logboeken blijven verborgen.","Protokoll wird geladen…":"Logboek wordt geladen…"
  }
};
function t(text){return (TEXTS[currentLang]&&TEXTS[currentLang][text])||text;}
function l(values){return values[currentLang]||values.en;}
const STATUS_TEXTS={
  de:{startup:"Startet",started:"Gestartet",stopped:"Gestoppt",unknown:"Unbekannt",error:"Fehler"},
  en:{startup:"Starting",started:"Started",stopped:"Stopped",unknown:"Unknown",error:"Error"},
  fr:{startup:"Démarrage",started:"Démarré",stopped:"Arrêté",unknown:"Inconnu",error:"Erreur"},
  es:{startup:"Iniciando",started:"Iniciado",stopped:"Detenido",unknown:"Desconocido",error:"Error"},
  nl:{startup:"Starten",started:"Gestart",stopped:"Gestopt",unknown:"Onbekend",error:"Fout"}
};
function localizedAddonState(state){
  const key=String(state||"unknown").toLowerCase();
  return (STATUS_TEXTS[currentLang]&&STATUS_TEXTS[currentLang][key])||state||"–";
}
function applyLanguage(language){
  const base=String(language||"en").toLowerCase().split("-")[0];
  currentLang=["de","en","fr","es","nl"].includes(base)?base:"en";
  document.documentElement.lang=currentLang;
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
  for(const node of nodes){
    const parent=node.parentElement;if(!parent||["SCRIPT","STYLE"].includes(parent.tagName))continue;
    const raw=node.nodeValue,trimmed=raw.trim();if(!trimmed)continue;
    const translated=t(trimmed);if(translated!==trimmed)node.nodeValue=raw.replace(trimmed,translated);
  }
  const tz=document.getElementById("cfg-TZ");
  if(tz)tz.placeholder=l({de:"leer = Home Assistant übernehmen",fr:"vide = reprendre Home Assistant",es:"vacío = usar Home Assistant",nl:"leeg = Home Assistant gebruiken",en:"empty = use Home Assistant"});
}
function selectedHomeAssistantLanguage() {
  const fallback = navigator.language || "en";
  try {
    const stored = window.localStorage.getItem("selectedLanguage");
    if (!stored) return fallback;
    try {
      const parsed = JSON.parse(stored);
      if (typeof parsed === "string" && parsed.trim()) return parsed;
    } catch (_error) {
      // Older/custom frontends may have stored the raw language directly.
    }
    return stored;
  } catch (_error) {
    return fallback;
  }
}
const CONFIG_KEYS=[
"SOURCE_MQTT_HOST","SOURCE_MQTT_PORT","SOURCE_MQTT_TLS","SOURCE_MQTT_USER","SOURCE_MQTT_PASS",
"TARGET_MQTT_HOST","TARGET_MQTT_PORT","TARGET_MQTT_TLS","TARGET_MQTT_USER","TARGET_MQTT_PASS",
"MQTT_CLIENT_SUFFIX","HA_BASE_TOPIC","GROWATT_CLOUD","GROWATT_CLOUD_CONFIG_FILTER","LOG_LEVEL",
"DUMP_MESSAGES","DUMP_DIR","REGISTER_DEBUG","REGISTER_DEBUG_DIR","REGISTER_DEBUG_MAX_REGISTER",
"REGISTER_DEBUG_CHANGES_ONLY","DEVICE_TIMEOUT","MAX_SLOTS","MAX_BAT",
"AVAILABILITY_SENSOR","TZ","KEEP_BATTERY_POSITION"];
const BOOL_KEYS=new Set(["SOURCE_MQTT_TLS","TARGET_MQTT_TLS","GROWATT_CLOUD","GROWATT_CLOUD_CONFIG_FILTER",
"DUMP_MESSAGES","REGISTER_DEBUG","REGISTER_DEBUG_CHANGES_ONLY",
"AVAILABILITY_SENSOR","KEEP_BATTERY_POSITION"]);
const INT_KEYS=new Set(["SOURCE_MQTT_PORT","TARGET_MQTT_PORT","REGISTER_DEBUG_MAX_REGISTER","DEVICE_TIMEOUT","MAX_SLOTS"]);

function apiUrl(suffix){const path=window.location.pathname.replace(/\/+$/,"");return path+"/"+suffix.replace(/^\/+/, "");}
function option(value,label,selected){const o=document.createElement("option");o.value=value;o.textContent=label;o.selected=selected;return o;}
function goBackToAddon(){try{if(window.history.length>1)window.history.back();}catch(e){console.warn(e);}}
function showMessage(id,text,kind="ok"){const el=document.getElementById(id);el.textContent=text;el.className="status "+kind;el.hidden=false;}

function activateTab(name){
  document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("active",x.id==="tab-"+name));
  document.querySelectorAll("[data-tab]").forEach(x=>x.classList.toggle("active",x.dataset.tab===name));
  if(logTimer){clearInterval(logTimer);logTimer=null;}
  if(name==="logs"){
    loadLogs().catch(showError);
    logTimer=setInterval(()=>loadLogs().catch(()=>{}),5000);
  }
}
document.querySelectorAll("[data-tab]").forEach(b=>b.addEventListener("click",()=>activateTab(b.dataset.tab)));
document.getElementById("back-top").addEventListener("click",goBackToAddon);

function currentDevice(){if(!batteryState)return null;const id=document.getElementById("device").value;return batteryState.devices.find(d=>d.device_id===id)||null;}
function configuredBatteryCount(device){
  const configured=configState&&configState.options?String(configState.options.MAX_BAT??"auto"):"auto";
  if(configured!=="auto"){
    const count=Number(configured);
    if(Number.isInteger(count))return Math.max(1,Math.min(4,count));
  }
  const detected=(device&&Array.isArray(device.detected))?device.detected:[];
  let highest=1;
  for(const item of detected){
    const slot=Number(item.physical_slot);
    if(Number.isInteger(slot))highest=Math.max(highest,Math.min(4,slot));
  }
  return highest;
}
function visibleAssignmentSlots(device){
  const maxBat=configuredBatteryCount(device);
  return [2,3,4].filter(slot=>slot<=maxBat);
}

function renderOverviewDevices(){
  const host=document.getElementById("overview-device-cards");
  const inventory=(batteryState&&Array.isArray(batteryState.inventory))?batteryState.inventory:[];
  host.replaceChildren();
  document.getElementById("summary-device-count").textContent=String(inventory.length);
  if(!inventory.length){
    const empty=document.createElement("div");empty.className="overview-empty";
    empty.textContent=l({de:"Noch keine Live-Telemetrie.",en:"No live telemetry yet.",fr:"Pas encore de télémétrie en direct.",es:"Aún no hay telemetría en vivo.",nl:"Nog geen live-telemetrie."});
    host.appendChild(empty);return;
  }
  for(const item of inventory){
    const card=document.createElement("div");card.className="device-card";
    const icon=document.createElement("div");icon.className="device-icon";
    icon.textContent=(item.display_name||"?").slice(0,5);
    const body=document.createElement("div");
    const name=document.createElement("strong");name.textContent=item.display_name||"UNKNOWN";
    const serial=document.createElement("div");serial.className="device-serial";serial.textContent=item.device_id||"";
    const online=document.createElement("div");online.className="online-line";
    online.textContent=l({de:"Live erkannt",en:"Detected live",fr:"Détecté en direct",es:"Detectado en vivo",nl:"Live gedetecteerd"});
    body.append(name,serial,online);

    const wifi=document.createElement("div");wifi.className="wifi-box";
    const bars=document.createElement("div");bars.className="wifi-bars";
    const rawSignalValue=item.wifi_signal_strength ?? item.wifi_signal ?? null;
    const rawSignal=Number(rawSignalValue);
    const dbm=(Number.isFinite(rawSignal) && rawSignal<0 && rawSignal>=-120)?rawSignal:NaN;
    let level=0;
    if(Number.isFinite(dbm)){
      level=dbm>=-55?4:dbm>=-65?3:dbm>=-75?2:1;
    }
    for(let i=1;i<=4;i++){
      const bar=document.createElement("span");if(i<=level)bar.className="on";bars.appendChild(bar);
    }
    const wifiValue=document.createElement("div");wifiValue.className="wifi-value";
    wifiValue.textContent=Number.isFinite(dbm)?Math.round(dbm)+" dBm":"–";
    wifi.append(bars,wifiValue);

    card.append(icon,body,wifi);host.appendChild(card);
  }
}

function clampSoc(value){
  if(value===null||value===undefined||value==="")return null;
  const number=Number(value);
  if(!Number.isFinite(number))return null;
  return Math.max(0,Math.min(100,number));
}

function renderOverviewBatteries(){
  const host=document.getElementById("overview-battery-cards");host.replaceChildren();
  const inventory=(batteryState&&Array.isArray(batteryState.inventory))?batteryState.inventory:[];
  const positionDevices=(batteryState&&Array.isArray(batteryState.devices))?batteryState.devices:[];
  const noahDevices=inventory.filter(item=>String(item.family||"").toLowerCase()==="noah");
  let count=0;

  for(const item of noahDevices){
    const positionDevice=positionDevices.find(device=>device.device_id===item.device_id)||{
      device_id:item.device_id,detected:[],automatic:{},manual:{}
    };
    const liveBatteries=Array.isArray(item.batteries)?item.batteries:[];
    for(const battery of liveBatteries){
      const slot=Number(battery.slot);
      if(!Number.isInteger(slot)||slot<1||slot>4)continue;
      count++;

      const soc=clampSoc(battery.soc);
      // The backend has already applied manual/stable slot remapping to
      // both serial fragments and measurements. Do not map them a second time.
      const serial=slot===1?item.device_id:(battery.serial||"");
      const card=document.createElement("div");card.className="battery-card";

      const icon=document.createElement("div");icon.className="battery-icon";
      const fill=document.createElement("span");fill.className="battery-fill";
      fill.style.height=(soc===null?0:soc)+"%";icon.appendChild(fill);

      const body=document.createElement("div");
      const title=document.createElement("strong");
      title.textContent="Bat "+slot;

      const serialLine=document.createElement("div");serialLine.className="muted";
      serialLine.textContent=serial||item.device_id;

      const assignment=document.createElement("div");assignment.className="battery-assignment";
      if(slot===1){
        assignment.textContent=l({de:"Master-Batterie",en:"Master battery",fr:"Batterie maître",es:"Batería maestra",nl:"Masterbatterij"});
      }else{
        const manual=serial&&positionDevice.manual&&positionDevice.manual[String(slot)]===serial;
        const stable=serial&&batteryState.keep_battery_position&&positionDevice.automatic&&positionDevice.automatic[String(slot)]===serial;
        assignment.textContent=manual
          ? l({de:"Manuell zugeordnet",en:"Manually assigned",fr:"Affectation manuelle",es:"Asignación manual",nl:"Handmatig toegewezen"})
          : stable
            ? l({de:"Stabil automatisch zugeordnet",en:"Stable automatic assignment",fr:"Affectation automatique stable",es:"Asignación automática estable",nl:"Stabiele automatische toewijzing"})
            : l({de:"Live erkannt",en:"Detected live",fr:"Détectée en direct",es:"Detectada en vivo",nl:"Live gedetecteerd"});
      }

      body.append(title,serialLine,assignment);

      const value=document.createElement("div");value.className="battery-value";
      value.textContent=soc===null?"–":Math.round(soc)+"%";
      const detail=document.createElement("small");
      detail.textContent=battery.temperature===undefined||battery.temperature===null
        ? l({de:"Live SoC",en:"Live SoC",fr:"SoC en direct",es:"SoC en vivo",nl:"Live SoC"})
        : Number(battery.temperature).toFixed(1)+" °C";
      value.appendChild(detail);

      card.append(icon,body,value);host.appendChild(card);
    }
  }

  if(!count){
    const empty=document.createElement("div");empty.className="overview-empty";
    empty.textContent=l({
      de:"Noch keine NOAH-Batteriedaten empfangen. Bat1 ist der NOAH Master; Bat2 bis Bat4 erscheinen automatisch, sobald sie vorhanden sind.",
      en:"No NOAH battery telemetry received yet. Bat1 is the NOAH master; Bat2 to Bat4 appear automatically when present.",
      fr:"Aucune télémétrie de batterie NOAH reçue. Bat1 est le maître NOAH ; Bat2 à Bat4 apparaissent automatiquement lorsqu'elles sont présentes.",
      es:"Aún no se recibió telemetría de batería NOAH. Bat1 es el maestro NOAH; Bat2 a Bat4 aparecen automáticamente cuando están presentes.",
      nl:"Nog geen NOAH-batterijtelemetrie ontvangen. Bat1 is de NOAH-master; Bat2 tot Bat4 verschijnen automatisch zodra ze aanwezig zijn."
    });
    host.appendChild(empty);
  }
}

async function loadOverviewLogs(){
  const output=document.getElementById("overview-log-output");
  try{
    const r=await fetch(apiUrl("api/logs"),{cache:"no-store"});const out=await r.json();
    if(!r.ok)throw new Error(out.error||"Log");
    const text=out.logs||"";
    const lines=text.split(/\r?\n/).filter(Boolean).slice(-9);
    output.textContent=lines.length?lines.join("\n"):l({de:"Noch keine Protokolleinträge seit dem Start.",en:"No log entries since startup.",fr:"Aucune entrée de journal depuis le démarrage.",es:"No hay entradas de registro desde el inicio.",nl:"Nog geen logboekvermeldingen sinds het starten."});
    output.scrollTop=output.scrollHeight;
  }catch(error){
    output.textContent=l({de:"Protokoll konnte nicht geladen werden.",en:"Could not load log.",fr:"Impossible de charger le journal.",es:"No se pudo cargar el registro.",nl:"Logboek kon niet worden geladen."});
  }
}

function renderBatteries(){
  const d=currentDevice(), detected=document.getElementById("detected");detected.replaceChildren();
  document.getElementById("battery-save").disabled=!d;
  const visibleSlots=visibleAssignmentSlots(d);
  for(const slot of [2,3,4]){
    const row=document.getElementById("row-slot"+slot);
    row.hidden=!visibleSlots.includes(slot);
  }
  if(!d){for(const slot of [2,3,4]){const c=document.getElementById("slot"+slot);c.replaceChildren(option(AUTO,t("Automatisch"),true));c.disabled=true;}return;}
  for(const e of d.detected){const chip=document.createElement("span");chip.className="chip";chip.textContent=e.serial+" ("+l({de:"physisch",fr:"physique",es:"física",nl:"fysiek",en:"physical"})+" Bat"+e.physical_slot+")";detected.appendChild(chip);}
  for(const slot of visibleSlots){
    const c=document.getElementById("slot"+slot), selected=d.manual[String(slot)]||AUTO, serials=d.detected.map(x=>x.serial);
    c.replaceChildren(option(AUTO,t("Automatisch"),selected===AUTO),option(EMPTY,t("Nicht belegt"),selected===EMPTY));
    if(selected!==AUTO&&selected!==EMPTY&&!serials.includes(selected))c.appendChild(option(selected,selected+" ("+l({de:"nicht erkannt",fr:"non détectée",es:"no detectada",nl:"niet gedetecteerd",en:"not detected"})+")",true));
    for(const serial of serials)c.appendChild(option(serial,serial,selected===serial));
    c.disabled=false;
    const automatic=d.automatic[String(slot)];
    document.getElementById("auto"+slot).textContent=automatic?t("Automatisch")+": "+automatic:t("Automatisch")+": "+(l({de:"noch nicht zugeordnet",fr:"pas encore attribuée",es:"aún no asignada",nl:"nog niet toegewezen",en:"not assigned yet"}));
  }
}
async function loadBatteries(){
  const r=await fetch(apiUrl("api/state"),{cache:"no-store"});if(!r.ok)throw new Error("Batteriestatus konnte nicht geladen werden");
  batteryState=await r.json();
  const summary=document.getElementById("summary-devices");summary.replaceChildren();
  const inventory=batteryState.inventory||[];
  if(!inventory.length){
    const none=document.createElement("span");none.className="muted";none.textContent=l({de:"Noch keine Live-Telemetrie",fr:"Pas encore de télémétrie en direct",es:"Aún no hay telemetría en vivo",nl:"Nog geen live-telemetrie",en:"No live telemetry yet"});summary.appendChild(none);
  }else{
    const counts={};
    for(const item of inventory)counts[item.display_name]=(counts[item.display_name]||0)+1;
    for(const name of Object.keys(counts).sort()){
      const chip=document.createElement("span");chip.className="chip";chip.textContent=counts[name]>1?name+" ×"+counts[name]:name;summary.appendChild(chip);
    }
  }
  const select=document.getElementById("device"),previous=select.value;select.replaceChildren();
  if(!batteryState.devices.length){select.appendChild(option("",t("Noch keine Batterie erkannt"),true));select.disabled=true;}
  else{select.disabled=false;for(const d of batteryState.devices)select.appendChild(option(d.device_id,d.device_id,d.device_id===previous));if(!select.value)select.selectedIndex=0;}
  renderBatteries();
  renderOverviewDevices();
  renderOverviewBatteries();
}
document.getElementById("device").addEventListener("change",renderBatteries);
document.getElementById("battery-save").addEventListener("click",async()=>{
  const d=currentDevice();if(!d)return;
  const slots=visibleAssignmentSlots(d);
  const values=slots.map(s=>document.getElementById("slot"+s).value),serials=values.filter(v=>v!==AUTO&&v!==EMPTY);
  if(new Set(serials).size!==serials.length){showMessage("battery-message",l({de:"Eine Seriennummer kann nur einer Position zugeordnet werden.",fr:"Un numéro de série ne peut être attribué qu'à une seule position.",es:"Un número de serie solo puede asignarse a una posición.",nl:"Een serienummer kan slechts aan één positie worden toegewezen.",en:"A serial number can only be assigned to one position."}),"error");return;}
  const assignments={};for(const slot of [2,3,4])assignments[String(slot)]=d.manual[String(slot)]||AUTO;
  slots.forEach((slot,i)=>assignments[String(slot)]=values[i]);
  const r=await fetch(apiUrl("api/assignments"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({device_id:d.device_id,assignments})});
  const out=await r.json();if(!r.ok){showMessage("battery-message",out.error||(l({de:"Speichern fehlgeschlagen",fr:"Échec de l'enregistrement",es:"Error al guardar",nl:"Opslaan mislukt",en:"Save failed"})),"error");return;}
  showMessage("battery-message",l({de:"Batterie-Zuordnung gespeichert. Rückkehr zum Add-on…",fr:"Affectation enregistrée. Retour à l'add-on…",es:"Asignación guardada. Volviendo al complemento…",nl:"Batterijtoewijzing opgeslagen. Terug naar de add-on…",en:"Battery assignment saved. Returning to add-on…"}));setTimeout(goBackToAddon, 900);
});

function fillConfig(options){
  for(const key of CONFIG_KEYS){const el=document.getElementById("cfg-"+key);if(!el)continue;const value=options[key];if(BOOL_KEYS.has(key))el.checked=Boolean(value);else el.value=value??"";}
}
document.getElementById("cfg-MAX_BAT").addEventListener("change",renderBatteries);
function collectConfig(){
  const out={};for(const key of CONFIG_KEYS){const el=document.getElementById("cfg-"+key);if(!el)continue;if(BOOL_KEYS.has(key))out[key]=el.checked;else if(INT_KEYS.has(key))out[key]=Number(el.value);else out[key]=el.value;}return out;
}
function collectConfigChanges(){
  if(configBaseline===null)throw new Error("Konfiguration konnte nicht geladen werden");
  const changes={};for(const [key,value] of Object.entries(collectConfig()))if(value!==configBaseline[key])changes[key]=value;
  return changes;
}
async function loadConfig(){
  const r=await fetch(apiUrl("api/config"),{cache:"no-store"});const out=await r.json();if(!r.ok)throw new Error(out.error||"Konfiguration konnte nicht geladen werden");
  configState=out;
  applyLanguage(out.language || selectedHomeAssistantLanguage());
  fillConfig(out.options||{});
  configBaseline=collectConfig();
  document.getElementById("summary-version").textContent=out.version||"–";
  document.getElementById("dashboard-version").textContent=out.version||"–";
  document.getElementById("summary-state").textContent=localizedAddonState(out.state);
  const overviewState=localizedAddonState(out.state);
  document.getElementById("overview-status-text").textContent=overviewState;
  const stateDot=document.getElementById("overview-status-dot");
  stateDot.classList.toggle("ok",String(out.state||"").toLowerCase().includes("started")||String(out.state||"").toLowerCase().includes("running"));
}
async function saveConfig(){
  const r=await fetch(apiUrl("api/config"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({options:collectConfigChanges()})});
  const out=await r.json();if(!r.ok){showMessage("config-message",out.error||(l({de:"Speichern fehlgeschlagen",fr:"Échec de l'enregistrement",es:"Error al guardar",nl:"Opslaan mislukt",en:"Save failed"})),"error");return;}
  showMessage("config-message",l({de:"Konfiguration gespeichert. Better GroBro wird neu gestartet…",fr:"Configuration enregistrée. Better GroBro redémarre…",es:"Configuración guardada. Better GroBro se reinicia…",nl:"Configuratie opgeslagen. Better GroBro wordt herstart…",en:"Configuration saved. Better GroBro is restarting…"}));setTimeout(goBackToAddon, 900);
}
for(const host of document.querySelectorAll(".config-actions")){
  const restart=document.createElement("button");restart.type="button";restart.textContent=t("Speichern & Better GroBro neu starten");restart.addEventListener("click",()=>saveConfig().catch(showError));
  host.append(restart);
}
const logOutput=document.getElementById("log-output");
logOutput.addEventListener("scroll",()=>{
  logFollowTail=logOutput.scrollHeight-logOutput.scrollTop-logOutput.clientHeight<20;
});

async function loadLogs(){
  const output=logOutput;
  const r=await fetch(apiUrl("api/logs"),{cache:"no-store"});
  const out=await r.json();
  if(!r.ok)throw new Error(out.error||"Protokoll konnte nicht geladen werden");
  document.getElementById("log-started").textContent=out.started_at?new Date(out.started_at).toLocaleString():"–";
  const nextText=out.marker_found?(out.logs||l({de:"Keine Protokolleinträge seit dem Start.",en:"No log entries since startup.",fr:"Aucune entrée de journal depuis le démarrage.",es:"No hay entradas de registro desde el inicio.",nl:"Geen logboekvermeldingen sinds het starten."})):l({de:"Warte auf den aktuellen Protokollbeginn…",en:"Waiting for the current log session…",fr:"En attente du journal de la session actuelle…",es:"Esperando el registro de la sesión actual…",nl:"Wachten op het huidige logboek…"});
  if(nextText===logLastText)return;

  const followTail=logFollowTail;
  const currentScrollTop=output.scrollTop;
  output.textContent=nextText;
  logLastText=nextText;

  if(followTail){
    output.scrollTop=output.scrollHeight;
  }else{
    output.scrollTop=Math.min(currentScrollTop,Math.max(0,output.scrollHeight-output.clientHeight));
    logFollowTail=false;
  }
}
document.getElementById("log-refresh").addEventListener("click",()=>loadLogs().catch(showError));
function showError(error){showMessage("config-message",error.message||String(error),"error");}
loadConfig().then(loadBatteries).then(loadOverviewLogs).catch(showError);
setInterval(()=>{
  const overview=document.getElementById("tab-overview");
  if(overview&&overview.classList.contains("active")){
    loadBatteries().catch(()=>{});
    loadOverviewLogs().catch(()=>{});
  }
},5000);
</script>
</body>
</html>
"""



class _HeaderDeadlineReader:
    """Keep BufferedReader semantics while enforcing one total header deadline."""
    def __init__(self, stream, connection, timeout=10):
        self._stream = stream
        self._connection = connection
        self._deadline = time.monotonic() + timeout

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def readline(self, limit=-1):
        previous = self._connection.gettimeout()
        line = bytearray()
        peek = getattr(self._stream, "peek", None)
        try:
            while limit < 0 or len(line) < limit:
                remaining = self._deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                self._connection.settimeout(remaining)
                if peek is not None:
                    # Consume only this line from bytes already buffered. Body
                    # bytes remain in the same stream for the POST reader.
                    buffered = peek(1)
                    size = buffered.find(b"\n") + 1 or len(buffered)
                    if limit >= 0:
                        size = min(size, limit - len(line))
                    value = self._stream.read(size)
                else:
                    value = self._stream.read(1)
                if not value:
                    break
                line.extend(value)
                if value.endswith(b"\n"):
                    break
            return bytes(line)
        finally:
            self._connection.settimeout(previous)

class BatteryIngressHandler(BaseHTTPRequestHandler):
    server_version = "BetterGroBroIngress/1.0"

    def setup(self):
        super().setup()
        self.rfile = _HeaderDeadlineReader(self.rfile, self.connection)

    def log_message(self, format, *args):  # noqa: A002
        LOG.debug("Ingress: " + format, *args)

    def _allowed(self) -> bool:
        return self.client_address[0] in _ALLOWED_CLIENTS

    def _send_body(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self._send_body(body, "application/json; charset=utf-8", status)

    def _send_html(self) -> None:
        self._send_body(_INDEX_HTML.encode(), "text/html; charset=utf-8")

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
            state = load_battery_ui_state()
            state["inventory"] = get_device_inventory()
            self._send_json(state)
            return
        if path.endswith("/api/config"):
            try:
                self._send_json(get_addon_options())
            except SupervisorConfigError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            return
        if path.endswith("/api/logs"):
            try:
                self._send_json(get_current_process_logs())
            except SupervisorConfigError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            return
        if path in {"", "/"} or "/api/hassio_ingress/" in path:
            self._send_html()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _read_json_body(self) -> dict | None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Ungültige Anfrage"}, HTTPStatus.BAD_REQUEST)
            return None
        if content_length <= 0 or content_length > 65536:
            self._send_json({"error": "Ungültige Anfragegröße"}, HTTPStatus.BAD_REQUEST)
            return None
        previous_timeout = self.connection.gettimeout()
        self.connection.settimeout(30)
        try:
            deadline = time.monotonic() + 30
            remaining = content_length
            chunks = []
            while remaining:
                budget = deadline - time.monotonic()
                if budget <= 0:
                    raise TimeoutError()
                self.connection.settimeout(budget)
                chunk = self.rfile.read1(remaining)
                if not chunk:
                    raise ValueError("Incomplete request body")
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = json.loads(b"".join(chunks))
        except TimeoutError:
            self.close_connection = True
            self._send_json({"error": "Ungültige Anfrage"}, HTTPStatus.REQUEST_TIMEOUT)
            return None
        except (ValueError, UnicodeDecodeError, RecursionError):
            self._send_json({"error": "Ungültiges JSON"}, HTTPStatus.BAD_REQUEST)
            return None
        finally:
            self.connection.settimeout(previous_timeout)
        if not isinstance(payload, dict):
            self._send_json({"error": "Ungültige Anfrage"}, HTTPStatus.BAD_REQUEST)
            return None
        return payload

    def do_POST(self) -> None:  # noqa: N802
        if self._reject_untrusted_client():
            return
        path = urlsplit(self.path).path.rstrip("/")
        payload = self._read_json_body()
        if payload is None:
            return

        if path.endswith("/api/config"):
            try:
                options = payload.get("options")
                if not isinstance(options, dict):
                    raise SupervisorConfigError("Ungültige Optionen")
                save_addon_options(options)
                self._send_json({"ok": True, "restart": True})
                schedule_restart()
            except SupervisorConfigError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if path.endswith("/api/assignments"):
            try:
                device_id = str(payload["device_id"]).strip()
                assignments = payload["assignments"]
                if not device_id or not isinstance(assignments, dict):
                    raise ValueError
                for slot in ("2", "3", "4"):
                    value = assignments.get(slot, AUTO_ASSIGNMENT)
                    if (
                        value not in {AUTO_ASSIGNMENT, EMPTY_ASSIGNMENT}
                        and not _is_plausible_serial(str(value))
                    ):
                        raise ValueError
                save_manual_assignments(device_id, assignments)
            except OSError:
                LOG.exception("Could not persist manual battery assignment")
                self._send_json({"error": "Ungültige Batterie-Zuordnung"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            except (KeyError, TypeError, ValueError):
                self._send_json(
                    {"error": "Ungültige Batterie-Zuordnung"},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json({"ok": True})
            return

        self.send_error(HTTPStatus.NOT_FOUND)



class BoundedIngressServer(ThreadingHTTPServer):
    """Bound request threads and incomplete headers without blocking accept."""
    daemon_threads = True

    def __init__(self, *args, max_requests: int = 8, **kwargs):
        self._request_slots = threading.BoundedSemaphore(max_requests)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(blocking=False):
            try:
                request.settimeout(0.25)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            request.settimeout(10)
            super().process_request(request, client_address)
        except Exception:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()

def start_battery_ingress_server(port: int = INGRESS_PORT) -> ThreadingHTTPServer:
    """Start the local Ingress HTTP service in a daemon thread."""
    import threading

    server = BoundedIngressServer(("0.0.0.0", port), BatteryIngressHandler)
    try:
        thread = threading.Thread(
            target=server.serve_forever,
            name="battery-ingress",
            daemon=True,
        )
        thread.start()
    except Exception:
        server.server_close()
        raise
    LOG.info("Battery assignment page is ready")
    return server
