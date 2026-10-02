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
      color-scheme: light dark;
      --bg:#101418; --card:#1c2228; --border:#343b43; --text:#e8eaed;
      --muted:#aeb6bf; --accent:#03a9f4; --danger:#ff6b6b; --ok:#62c96b;
      --secondary:#2a3138; --warning:#c58b16;
    }
    * { box-sizing:border-box; }
    body { margin:0; font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); }
    main { max-width:1100px; margin:0 auto; padding:22px; }
    h1 { margin:0 0 4px; font-size:26px; } h2 { margin:0 0 14px; font-size:19px; } h3 { margin:18px 0 10px; font-size:15px; }
    p { margin:0; } .muted { color:var(--muted); }
    .header { display:flex; justify-content:space-between; align-items:center; gap:14px; flex-wrap:wrap; }
    .tabs { display:flex; gap:6px; flex-wrap:wrap; margin:18px 0; padding-bottom:10px; border-bottom:1px solid var(--border); }
    .tabs button { min-width:0; }
    .tabs button.active { background:var(--accent); color:#00131d; border-color:transparent; }
    .tab { display:none; } .tab.active { display:block; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:18px; margin-top:14px; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px 18px; }
    .field { min-width:0; } .field.full { grid-column:1/-1; }
    label { display:block; font-weight:600; margin-bottom:5px; }
    .help { color:var(--muted); font-size:12px; margin-top:4px; }
    input, select, button { min-height:42px; border-radius:8px; border:1px solid var(--border); background:#151a1f; color:var(--text); padding:8px 11px; font:inherit; }
    input,select { width:100%; } input[type="checkbox"] { width:auto; min-height:auto; transform:scale(1.15); margin-right:8px; }
    .check { display:flex; align-items:center; min-height:42px; }
    button { cursor:pointer; background:var(--accent); color:#00131d; border-color:transparent; font-weight:700; }
    button.secondary { background:var(--secondary); color:var(--text); border-color:var(--border); }
    button:disabled { opacity:.55; cursor:default; }
    .actions { display:flex; justify-content:flex-end; gap:10px; flex-wrap:wrap; margin-top:18px; }
    .status { margin-top:14px; border-radius:8px; padding:10px 12px; border:1px solid var(--border); }
    .status.ok { border-color:var(--ok); } .status.error { border-color:var(--danger); color:#ffd2d2; }
    .status.warning { border-color:var(--warning); background:#2a2417; }
    .serials { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
    .chip { border:1px solid var(--border); border-radius:999px; padding:5px 9px; color:var(--muted); }
    .battery-row { display:grid; grid-template-columns:minmax(180px,1fr) minmax(280px,1.4fr); gap:18px; align-items:center; padding:12px 0; border-top:1px solid var(--border); }
    [hidden] { display:none !important; }
    .battery-row:first-of-type { border-top:0; }
    .summary { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
    .metric { background:#151a1f; border:1px solid var(--border); border-radius:10px; padding:14px; }
    .metric strong { display:block; font-size:20px; margin-top:4px; }
    .section-note { margin-top:12px; color:var(--muted); font-size:12px; }
    .log-toolbar { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:12px; }
    .log-output { margin:0; height:420px; min-height:420px; max-height:420px; overflow-y:auto; overflow-x:auto; overscroll-behavior:contain; scrollbar-gutter:stable; touch-action:pan-y; -webkit-overflow-scrolling:touch; -webkit-text-size-adjust:100%; text-size-adjust:100%; white-space:pre; word-break:normal; background:#0b0f12; border:1px solid var(--border); border-radius:8px; padding:14px; font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace; color:var(--text); }
    @media (max-width:760px) {
      main{padding:15px}.grid,.summary,.battery-row{grid-template-columns:1fr}.actions button,.header button{width:100%}
    }
  </style>
</head>
<body>
<main>
  <div class="header">
    <div>
      <h1>Better GroBro</h1>
      <p class="muted">Konfiguration und Batterie-Zuordnung</p>
    </div>
    <button id="back-top" type="button" class="secondary">Zurück zum Add-on</button>
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
    <div class="summary">
      <div class="metric"><span class="muted">Version</span><strong id="summary-version">–</strong></div>
      <div class="metric"><span class="muted">Add-on Status</span><strong id="summary-state">–</strong></div>
      <div class="metric"><span class="muted">Erkannte Geräte</span><div id="summary-devices" class="serials"><span class="muted">–</span></div></div>
    </div>
    <div class="card">
      <h2>Empfohlene Konfiguration</h2>
      <p>Verwende bevorzugt diese Better-GroBro-Oberfläche. Sie bearbeitet direkt die offiziellen Home-Assistant-Add-on-Optionen; der native Konfiguration-Tab bleibt als Fallback verfügbar und verwendet dieselben Werte.</p>
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
let batteryState=null, configState=null, currentLang="de", logTimer=null, logFollowTail=true, logLastText=null;
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
async function loadConfig(){
  const r=await fetch(apiUrl("api/config"),{cache:"no-store"});const out=await r.json();if(!r.ok)throw new Error(out.error||"Konfiguration konnte nicht geladen werden");
  configState=out;
  applyLanguage(out.language || selectedHomeAssistantLanguage());
  fillConfig(out.options||{});
  document.getElementById("summary-version").textContent=out.version||"–";
  document.getElementById("summary-state").textContent=localizedAddonState(out.state);
}
async function saveConfig(){
  const r=await fetch(apiUrl("api/config"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({options:collectConfig()})});
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
loadConfig().then(loadBatteries).catch(showError);
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
        try:
            while limit < 0 or len(line) < limit:
                remaining = self._deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                self._connection.settimeout(remaining)
                # BufferedReader.read(1) uses its existing buffer; no packet over-read.
                value = self._stream.read(1)
                if not value:
                    break
                line.extend(value)
                if value == b"\n":
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
