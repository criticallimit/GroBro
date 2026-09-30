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
from grobro.ha.device_inventory import get_device_inventory
from grobro.ha.supervisor_config import (
    SupervisorConfigError,
    get_addon_options,
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
      <div class="actions"><button id="back-bottom" type="button" class="secondary">Zurück</button><button id="battery-save" type="button">Batterie-Zuordnung speichern</button></div>
      <div id="battery-message" class="status" hidden></div>
    </div>
  </section>

  <section id="tab-ha" class="tab">
    <div class="card">
      <h2>Home Assistant</h2>
      <div class="grid">
        <div class="field"><label>Stabile Batteriepositionen</label><div class="check"><input id="cfg-KEEP_BATTERY_POSITION" type="checkbox">NOAH/NEXA per Seriennummer stabil halten</div></div>
        <div class="field"><label for="cfg-MAX_BAT">Maximale Batterieanzahl</label><select id="cfg-MAX_BAT"><option value="auto">Automatisch</option><option>1</option><option>2</option><option>3</option><option>4</option></select></div>
        <div class="field"><label for="cfg-MAX_SLOTS">Zeitfenster</label><select id="cfg-MAX_SLOTS"><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option><option>6</option><option>7</option><option>8</option><option>9</option></select><div class="help">Anzahl der Batterie-Zeitfenster in Home Assistant.</div></div>
        <div class="field"><label for="cfg-DEVICE_TIMEOUT">Geräte-Timeout (Sekunden)</label><input id="cfg-DEVICE_TIMEOUT" type="number" min="1" step="1"><div class="help">Nach dieser Zeit ohne Telemetrie werden die Entities unavailable, bleiben aber in Home Assistant erhalten.</div></div>
        <div class="field"><label>Availability-Sensor</label><div class="check"><input id="cfg-AVAILABILITY_SENSOR" type="checkbox">Zusätzlichen Online-Sensor erzeugen</div></div>
        <div class="field"><label>Messwertsprünge filtern</label><div class="check"><input id="cfg-FILTER_DATA_GLITCHES" type="checkbox">Rücksprünge bei total_increasing unterdrücken</div></div>
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

  <div id="config-message" class="status" hidden></div>
</main>

<script>
const AUTO="__auto__", EMPTY="__empty__";
let batteryState=null, configState=null, currentLang="de";
const TEXTS={
  en:{
    "Konfiguration und Batterie-Zuordnung":"Configuration and battery assignment","Zurück zum Add-on":"Back to add-on",
    "Übersicht":"Overview","Batterien":"Batteries","Diagnose":"Diagnostics","Version":"Version","Add-on Status":"Add-on status",
    "Erkannte Geräte":"Detected devices","Empfohlene Konfiguration":"Recommended configuration",
    "Verwende bevorzugt diese Better-GroBro-Oberfläche. Sie bearbeitet direkt die offiziellen Home-Assistant-Add-on-Optionen; der native Konfiguration-Tab bleibt als Fallback verfügbar und verwendet dieselben Werte.":"Prefer this Better GroBro interface. It edits the official Home Assistant add-on options directly; the native Configuration tab remains available as a fallback and uses the same values.",
    "Änderungen an Better-GroBro-Optionen werden beim Start geladen. Verwende daher nach Änderungen vorzugsweise":"Changes to Better GroBro options are loaded at startup. After changing options, preferably use",
    "Speichern & Better GroBro neu starten":"Save & restart Better GroBro","Batterie-Zuordnung":"Battery assignment","Bat1 (Master)":"Bat1 (Master)",
    "Zurück":"Back","Batterie-Zuordnung speichern":"Save battery assignment","Stabile Batteriepositionen":"Stable battery positions",
    "NOAH/NEXA per Seriennummer stabil halten":"Keep NOAH/NEXA stable by serial number","Maximale Batterieanzahl":"Maximum battery count",
    "Automatisch":"Automatic","Zeitfenster":"Time slots","Anzahl der Batterie-Zeitfenster in Home Assistant.":"Number of battery scheduling slots in Home Assistant.",
    "Geräte-Timeout (Sekunden)":"Device timeout (seconds)","Nach dieser Zeit ohne Telemetrie werden die Entities unavailable, bleiben aber in Home Assistant erhalten.":"After this time without telemetry, entities become unavailable but remain in Home Assistant.",
    "Availability-Sensor":"Availability sensor","Zusätzlichen Online-Sensor erzeugen":"Create an additional online sensor",
    "Messwertsprünge filtern":"Filter data glitches","Rücksprünge bei total_increasing unterdrücken":"Suppress decreases in total_increasing values",
    
    "HA Basis-Topic":"HA base topic","MQTT Client-Suffix":"MQTT client suffix","Zeitzone":"Timezone",
    "Growatt / Quell-MQTT":"Growatt / source MQTT","Host":"Host","Port":"Port","Benutzername":"Username","Passwort":"Password",
    "TLS aktivieren":"Enable TLS","Home Assistant / Ziel-MQTT":"Home Assistant / target MQTT","Cloud-Weiterleitung":"Cloud forwarding",
    "Nachrichten zur/von der Growatt Cloud weiterleiten":"Forward messages to/from Growatt Cloud","Konfigurationsfilter":"Configuration filter",
    "Ferninitiierte Konfigurationsnachrichten blockieren":"Block remotely initiated configuration messages","Log-Level":"Log level",
    "Roh-Nachrichten speichern":"Store raw messages","Raw MQTT Dump aktivieren":"Enable raw MQTT dump","Dump-Verzeichnis":"Dump directory",
    "Register-Debug":"Register debug","Passiven Register-Debugger aktivieren":"Enable passive register debugger","Nur Änderungen":"Changes only",
    "Nach Erstwert nur Änderungen protokollieren":"After first value, log changes only","Maximales Register":"Maximum register",
    "Register-Debug-Verzeichnis":"Register debug directory","Nur speichern":"Save only","Nicht belegt":"Not occupied",
    "Noch keine Batterie erkannt":"No battery detected yet"
  },
  fr:{
    "Konfiguration und Batterie-Zuordnung":"Configuration et affectation des batteries","Zurück zum Add-on":"Retour à l'add-on",
    "Übersicht":"Vue d'ensemble","Batterien":"Batteries","Diagnose":"Diagnostic","Version":"Version","Add-on Status":"État de l'add-on",
    "Erkannte Geräte":"Appareils détectés","Empfohlene Konfiguration":"Configuration recommandée",
    "Verwende bevorzugt diese Better-GroBro-Oberfläche. Sie bearbeitet direkt die offiziellen Home-Assistant-Add-on-Optionen; der native Konfiguration-Tab bleibt als Fallback verfügbar und verwendet dieselben Werte.":"Utilisez de préférence cette interface Better GroBro. Elle modifie directement les options officielles de l'add-on Home Assistant ; l'onglet Configuration natif reste disponible comme solution de secours et utilise les mêmes valeurs.",
    "Änderungen an Better-GroBro-Optionen werden beim Start geladen. Verwende daher nach Änderungen vorzugsweise":"Les modifications des options Better GroBro sont chargées au démarrage. Après une modification, utilisez de préférence",
    "Speichern & Better GroBro neu starten":"Enregistrer et redémarrer Better GroBro","Batterie-Zuordnung":"Affectation des batteries","Bat1 (Master)":"Bat1 (Master)",
    "Zurück":"Retour","Batterie-Zuordnung speichern":"Enregistrer l'affectation","Stabile Batteriepositionen":"Positions de batterie stables",
    "NOAH/NEXA per Seriennummer stabil halten":"Maintenir NOAH/NEXA stables par numéro de série","Maximale Batterieanzahl":"Nombre maximal de batteries",
    "Automatisch":"Automatique","Zeitfenster":"Créneaux horaires","Anzahl der Batterie-Zeitfenster in Home Assistant.":"Nombre de créneaux de batterie dans Home Assistant.",
    "Geräte-Timeout (Sekunden)":"Délai de l'appareil (secondes)","Nach dieser Zeit ohne Telemetrie werden die Entities unavailable, bleiben aber in Home Assistant erhalten.":"Après ce délai sans télémétrie, les entités deviennent indisponibles mais restent dans Home Assistant.",
    "Availability-Sensor":"Capteur de disponibilité","Zusätzlichen Online-Sensor erzeugen":"Créer un capteur en ligne supplémentaire",
    "Messwertsprünge filtern":"Filtrer les anomalies","Rücksprünge bei total_increasing unterdrücken":"Supprimer les diminutions de total_increasing",
    
    "HA Basis-Topic":"Topic de base HA","MQTT Client-Suffix":"Suffixe client MQTT","Zeitzone":"Fuseau horaire",
    "Growatt / Quell-MQTT":"Growatt / MQTT source","Host":"Hôte","Port":"Port","Benutzername":"Nom d'utilisateur","Passwort":"Mot de passe",
    "TLS aktivieren":"Activer TLS","Home Assistant / Ziel-MQTT":"Home Assistant / MQTT cible","Cloud-Weiterleitung":"Transfert cloud",
    "Nachrichten zur/von der Growatt Cloud weiterleiten":"Transférer les messages vers/depuis Growatt Cloud","Konfigurationsfilter":"Filtre de configuration",
    "Ferninitiierte Konfigurationsnachrichten blockieren":"Bloquer les changements de configuration distants","Log-Level":"Niveau de journal",
    "Roh-Nachrichten speichern":"Enregistrer les messages bruts","Raw MQTT Dump aktivieren":"Activer le dump MQTT brut","Dump-Verzeichnis":"Répertoire du dump",
    "Register-Debug":"Débogage registres","Passiven Register-Debugger aktivieren":"Activer le débogueur passif des registres","Nur Änderungen":"Modifications uniquement",
    "Nach Erstwert nur Änderungen protokollieren":"Après la première valeur, journaliser uniquement les changements","Maximales Register":"Registre maximal",
    "Register-Debug-Verzeichnis":"Répertoire de débogage des registres","Nur speichern":"Enregistrer seulement",
    "Nicht belegt":"Non occupé","Noch keine Batterie erkannt":"Aucune batterie détectée"
  },
  es:{
    "Konfiguration und Batterie-Zuordnung":"Configuración y asignación de baterías","Zurück zum Add-on":"Volver al complemento",
    "Übersicht":"Resumen","Batterien":"Baterías","Diagnose":"Diagnóstico","Version":"Versión","Add-on Status":"Estado del complemento",
    "Erkannte Geräte":"Dispositivos detectados","Empfohlene Konfiguration":"Configuración recomendada",
    "Verwende bevorzugt diese Better-GroBro-Oberfläche. Sie bearbeitet direkt die offiziellen Home-Assistant-Add-on-Optionen; der native Konfiguration-Tab bleibt als Fallback verfügbar und verwendet dieselben Werte.":"Use preferentemente esta interfaz de Better GroBro. Edita directamente las opciones oficiales del complemento de Home Assistant; la pestaña Configuración nativa permanece disponible como respaldo y utiliza los mismos valores.",
    "Änderungen an Better-GroBro-Optionen werden beim Start geladen. Verwende daher nach Änderungen vorzugsweise":"Los cambios de Better GroBro se cargan al iniciar. Después de cambiar opciones, use preferiblemente",
    "Speichern & Better GroBro neu starten":"Guardar y reiniciar Better GroBro","Batterie-Zuordnung":"Asignación de baterías","Bat1 (Master)":"Bat1 (Master)",
    "Zurück":"Volver","Batterie-Zuordnung speichern":"Guardar asignación","Stabile Batteriepositionen":"Posiciones estables de batería",
    "NOAH/NEXA per Seriennummer stabil halten":"Mantener NOAH/NEXA estables por número de serie","Maximale Batterieanzahl":"Número máximo de baterías",
    "Automatisch":"Automático","Zeitfenster":"Franjas horarias","Anzahl der Batterie-Zeitfenster in Home Assistant.":"Número de franjas de batería en Home Assistant.",
    "Geräte-Timeout (Sekunden)":"Tiempo de espera del dispositivo (segundos)","Nach dieser Zeit ohne Telemetrie werden die Entities unavailable, bleiben aber in Home Assistant erhalten.":"Tras este tiempo sin telemetría, las entidades pasan a no disponibles pero permanecen en Home Assistant.",
    "Availability-Sensor":"Sensor de disponibilidad","Zusätzlichen Online-Sensor erzeugen":"Crear un sensor en línea adicional",
    "Messwertsprünge filtern":"Filtrar anomalías","Rücksprünge bei total_increasing unterdrücken":"Suprimir descensos en total_increasing",
    "HA Basis-Topic":"Topic base de HA","MQTT Client-Suffix":"Sufijo de cliente MQTT","Zeitzone":"Zona horaria",
    "Growatt / Quell-MQTT":"Growatt / MQTT origen","Host":"Host","Port":"Puerto","Benutzername":"Usuario","Passwort":"Contraseña",
    "TLS aktivieren":"Activar TLS","Home Assistant / Ziel-MQTT":"Home Assistant / MQTT destino","Cloud-Weiterleitung":"Reenvío a la nube",
    "Nachrichten zur/von der Growatt Cloud weiterleiten":"Reenviar mensajes hacia/desde Growatt Cloud","Konfigurationsfilter":"Filtro de configuración",
    "Ferninitiierte Konfigurationsnachrichten blockieren":"Bloquear cambios de configuración remotos","Log-Level":"Nivel de registro",
    "Roh-Nachrichten speichern":"Guardar mensajes sin procesar","Raw MQTT Dump aktivieren":"Activar volcado MQTT","Dump-Verzeichnis":"Directorio de volcado",
    "Register-Debug":"Depuración de registros","Passiven Register-Debugger aktivieren":"Activar depurador pasivo de registros","Nur Änderungen":"Solo cambios",
    "Nach Erstwert nur Änderungen protokollieren":"Tras el primer valor, registrar solo cambios","Maximales Register":"Registro máximo",
    "Register-Debug-Verzeichnis":"Directorio de depuración de registros","Nur speichern":"Solo guardar","Nicht belegt":"No ocupado",
    "Noch keine Batterie erkannt":"Aún no se detectó ninguna batería"
  }
};
function t(text){return (TEXTS[currentLang]&&TEXTS[currentLang][text])||text;}
const STATUS_TEXTS={
  de:{startup:"Startet",started:"Gestartet",stopped:"Gestoppt",unknown:"Unbekannt",error:"Fehler"},
  en:{startup:"Starting",started:"Started",stopped:"Stopped",unknown:"Unknown",error:"Error"},
  fr:{startup:"Démarrage",started:"Démarré",stopped:"Arrêté",unknown:"Inconnu",error:"Erreur"},
  es:{startup:"Iniciando",started:"Iniciado",stopped:"Detenido",unknown:"Desconocido",error:"Error"}
};
function localizedAddonState(state){
  const key=String(state||"unknown").toLowerCase();
  return (STATUS_TEXTS[currentLang]&&STATUS_TEXTS[currentLang][key])||state||"–";
}
function applyLanguage(language){
  const base=String(language||"en").toLowerCase().split("-")[0];
  currentLang=["de","en","fr","es"].includes(base)?base:"en";
  document.documentElement.lang=currentLang;
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
  for(const node of nodes){
    const parent=node.parentElement;if(!parent||["SCRIPT","STYLE"].includes(parent.tagName))continue;
    const raw=node.nodeValue,trimmed=raw.trim();if(!trimmed)continue;
    const translated=t(trimmed);if(translated!==trimmed)node.nodeValue=raw.replace(trimmed,translated);
  }
  const tz=document.getElementById("cfg-TZ");
  if(tz)tz.placeholder=currentLang==="de"?"leer = Home Assistant übernehmen":currentLang==="fr"?"vide = reprendre Home Assistant":currentLang==="es"?"vacío = usar Home Assistant":"empty = use Home Assistant";
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
"AVAILABILITY_SENSOR","FILTER_DATA_GLITCHES","TZ","KEEP_BATTERY_POSITION"];
const BOOL_KEYS=new Set(["SOURCE_MQTT_TLS","TARGET_MQTT_TLS","GROWATT_CLOUD","GROWATT_CLOUD_CONFIG_FILTER",
"DUMP_MESSAGES","REGISTER_DEBUG","REGISTER_DEBUG_CHANGES_ONLY",
"AVAILABILITY_SENSOR","FILTER_DATA_GLITCHES","KEEP_BATTERY_POSITION"]);
const INT_KEYS=new Set(["SOURCE_MQTT_PORT","TARGET_MQTT_PORT","REGISTER_DEBUG_MAX_REGISTER","DEVICE_TIMEOUT","MAX_SLOTS"]);

function apiUrl(suffix){const path=window.location.pathname.replace(/\/+$/,"");return path+"/"+suffix.replace(/^\/+/, "");}
function option(value,label,selected){const o=document.createElement("option");o.value=value;o.textContent=label;o.selected=selected;return o;}
function goBackToAddon(){try{if(window.history.length>1)window.history.back();}catch(e){console.warn(e);}}
function showMessage(id,text,kind="ok"){const el=document.getElementById(id);el.textContent=text;el.className="status "+kind;el.hidden=false;}

function activateTab(name){
  document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("active",x.id==="tab-"+name));
  document.querySelectorAll("[data-tab]").forEach(x=>x.classList.toggle("active",x.dataset.tab===name));
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
  for(const e of d.detected){const chip=document.createElement("span");chip.className="chip";chip.textContent=e.serial+" ("+(currentLang==="de"?"physisch":currentLang==="fr"?"physique":currentLang==="es"?"física":"physical")+" Bat"+e.physical_slot+")";detected.appendChild(chip);}
  for(const slot of visibleSlots){
    const c=document.getElementById("slot"+slot), selected=d.manual[String(slot)]||AUTO, serials=d.detected.map(x=>x.serial);
    c.replaceChildren(option(AUTO,t("Automatisch"),selected===AUTO),option(EMPTY,t("Nicht belegt"),selected===EMPTY));
    if(selected!==AUTO&&selected!==EMPTY&&!serials.includes(selected))c.appendChild(option(selected,selected+" ("+(currentLang==="de"?"nicht erkannt":currentLang==="fr"?"non détectée":currentLang==="es"?"no detectada":"not detected")+")",true));
    for(const serial of serials)c.appendChild(option(serial,serial,selected===serial));
    c.disabled=false;
    const automatic=d.automatic[String(slot)];
    document.getElementById("auto"+slot).textContent=automatic?t("Automatisch")+": "+automatic:t("Automatisch")+": "+(currentLang==="de"?"noch nicht zugeordnet":currentLang==="fr"?"pas encore attribuée":currentLang==="es"?"aún no asignada":"not assigned yet");
  }
}
async function loadBatteries(){
  const r=await fetch(apiUrl("api/state"),{cache:"no-store"});if(!r.ok)throw new Error("Batteriestatus konnte nicht geladen werden");
  batteryState=await r.json();
  const summary=document.getElementById("summary-devices");summary.replaceChildren();
  const inventory=batteryState.inventory||[];
  if(!inventory.length){
    const none=document.createElement("span");none.className="muted";none.textContent=currentLang==="de"?"Noch keine Live-Telemetrie":currentLang==="fr"?"Pas encore de télémétrie en direct":currentLang==="es"?"Aún no hay telemetría en vivo":"No live telemetry yet";summary.appendChild(none);
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
document.getElementById("back-bottom").addEventListener("click",goBackToAddon);
document.getElementById("battery-save").addEventListener("click",async()=>{
  const d=currentDevice();if(!d)return;
  const slots=visibleAssignmentSlots(d);
  const values=slots.map(s=>document.getElementById("slot"+s).value),serials=values.filter(v=>v!==AUTO&&v!==EMPTY);
  if(new Set(serials).size!==serials.length){showMessage("battery-message",currentLang==="de"?"Eine Seriennummer kann nur einer Position zugeordnet werden.":currentLang==="fr"?"Un numéro de série ne peut être attribué qu'à une seule position.":currentLang==="es"?"Un número de serie solo puede asignarse a una posición.":"A serial number can only be assigned to one position.","error");return;}
  const assignments={};for(const slot of [2,3,4])assignments[String(slot)]=d.manual[String(slot)]||AUTO;
  slots.forEach((slot,i)=>assignments[String(slot)]=values[i]);
  const r=await fetch(apiUrl("api/assignments"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({device_id:d.device_id,assignments})});
  const out=await r.json();if(!r.ok){showMessage("battery-message",out.error||(currentLang==="de"?"Speichern fehlgeschlagen":currentLang==="fr"?"Échec de l'enregistrement":currentLang==="es"?"Error al guardar":"Save failed"),"error");return;}
  showMessage("battery-message",currentLang==="de"?"Batterie-Zuordnung gespeichert. Rückkehr zum Add-on…":currentLang==="fr"?"Affectation enregistrée. Retour à l'add-on…":currentLang==="es"?"Asignación guardada. Volviendo al complemento…":"Battery assignment saved. Returning to add-on…");setTimeout(goBackToAddon, 900);
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
async function saveConfig(restart){
  const r=await fetch(apiUrl("api/config"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({options:collectConfig(),restart})});
  const out=await r.json();if(!r.ok){showMessage("config-message",out.error||(currentLang==="de"?"Speichern fehlgeschlagen":currentLang==="fr"?"Échec de l'enregistrement":currentLang==="es"?"Error al guardar":"Save failed"),"error");return;}
  if(restart){showMessage("config-message",currentLang==="de"?"Konfiguration gespeichert. Better GroBro wird neu gestartet…":currentLang==="fr"?"Configuration enregistrée. Better GroBro redémarre…":currentLang==="es"?"Configuración guardada. Better GroBro se reinicia…":"Configuration saved. Better GroBro is restarting…");setTimeout(goBackToAddon, 900);}
  else showMessage("config-message",currentLang==="de"?"Konfiguration gespeichert. Neustart erforderlich, damit alle Änderungen aktiv werden.":currentLang==="fr"?"Configuration enregistrée. Un redémarrage est nécessaire pour appliquer toutes les modifications.":currentLang==="es"?"Configuración guardada. Se requiere reiniciar para aplicar todos los cambios.":"Configuration saved. Restart required for all changes to become active.","warning");
}
for(const host of document.querySelectorAll(".config-actions")){
  const only=document.createElement("button");only.type="button";only.className="secondary";only.textContent=t("Nur speichern");only.addEventListener("click",()=>saveConfig(false).catch(showError));
  const restart=document.createElement("button");restart.type="button";restart.textContent=t("Speichern & Better GroBro neu starten");restart.addEventListener("click",()=>saveConfig(true).catch(showError));
  host.append(only,restart);
}
function showError(error){showMessage("config-message",error.message||String(error),"error");}
loadConfig().then(loadBatteries).catch(showError);
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
        try:
            payload = json.loads(self.rfile.read(content_length))
        except json.JSONDecodeError:
            self._send_json({"error": "Ungültiges JSON"}, HTTPStatus.BAD_REQUEST)
            return None
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
                restart = payload.get("restart") is True
                self._send_json({"ok": True, "restart": restart})
                if restart:
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
            except (KeyError, TypeError, ValueError):
                self._send_json(
                    {"error": "Ungültige Batterie-Zuordnung"},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json({"ok": True})
            return

        self.send_error(HTTPStatus.NOT_FOUND)


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
