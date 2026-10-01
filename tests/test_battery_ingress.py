import json
import urllib.request

from grobro.ha import battery_ingress
from grobro.ha.battery_ingress import start_battery_ingress_server
from grobro.ha.battery_position import (
    AUTO_ASSIGNMENT,
    observe_battery_serials,
)
from grobro.ha.device_inventory import clear_device_inventory, observe_device


def test_ingress_api_lists_and_saves_battery_assignments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = type("Client", (), {})()
    observe_battery_serials(
        client,
        "0PVPTEST",
        {
            "bat2_ser_part_1": "SN00200000000001",
            "bat3_ser_part_1": "SN00300000000002",
        },
    )

    server = start_battery_ingress_server(0)
    host, port = server.server_address
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{base}/api/state", timeout=3) as response:
            state = json.load(response)

        assert state["devices"][0]["device_id"] == "0PVPTEST"
        assert [item["serial"] for item in state["devices"][0]["detected"]] == [
            "SN00200000000001",
            "SN00300000000002",
        ]

        payload = json.dumps(
            {
                "device_id": "0PVPTEST",
                "assignments": {
                    "2": "SN00300000000002",
                    "3": "SN00200000000001",
                    "4": AUTO_ASSIGNMENT,
                },
            }
        ).encode()
        request = urllib.request.Request(
            f"{base}/api/assignments",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.load(response)

        assert result == {"ok": True}

        with urllib.request.urlopen(f"{base}/api/state", timeout=3) as response:
            state = json.load(response)

        manual = state["devices"][0]["manual"]
        assert manual["2"] == "SN00300000000002"
        assert manual["3"] == "SN00200000000001"
        assert manual["4"] == AUTO_ASSIGNMENT
    finally:
        server.shutdown()
        server.server_close()


def test_ingress_rejects_duplicate_serial_assignments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        payload = json.dumps(
            {
                "device_id": "0PVPTEST",
                "assignments": {
                    "2": "SN00200000000001",
                    "3": "SN00200000000001",
                    "4": AUTO_ASSIGNMENT,
                },
            }
        ).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/assignments",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("duplicate serial assignment was accepted")
    finally:
        server.shutdown()
        server.server_close()


def test_ingress_page_has_single_back_navigation_and_auto_return():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert 'id="back-top"' in html
        assert 'id="back-bottom"' not in html
        assert "window.history.back()" in html
        assert "setTimeout(goBackToAddon, 900)" in html
    finally:
        server.shutdown()
        server.server_close()


def test_ingress_config_api_reads_and_saves_supervisor_options(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    saved = {}
    restarted = []

    monkeypatch.setattr(
        battery_ingress,
        "get_addon_options",
        lambda: {
            "version": "3.1.28",
            "state": "started",
            "options": {
                "SOURCE_MQTT_HOST": "growatt.local",
                "KEEP_BATTERY_POSITION": False,
            },
        },
    )

    def fake_save(options):
        saved.update(options)
        return options

    monkeypatch.setattr(battery_ingress, "save_addon_options", fake_save)
    monkeypatch.setattr(
        battery_ingress,
        "schedule_restart",
        lambda: restarted.append(True),
    )

    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{base}/api/config", timeout=3) as response:
            state = json.load(response)

        assert state["version"] == "3.1.28"
        assert state["options"]["SOURCE_MQTT_HOST"] == "growatt.local"

        payload = json.dumps(
            {
                "options": {
                    "SOURCE_MQTT_HOST": "new.local",
                    "KEEP_BATTERY_POSITION": True,
                },
            }
        ).encode()
        request = urllib.request.Request(
            f"{base}/api/config",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.load(response)

        assert result == {"ok": True, "restart": True}
        assert saved == {
            "SOURCE_MQTT_HOST": "new.local",
            "KEEP_BATTERY_POSITION": True,
        }
        assert restarted == [True]
    finally:
        server.shutdown()
        server.server_close()


def test_ingress_page_contains_full_configuration_sections():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        for label in (
            "Home Assistant",
            "MQTT",
            "Growatt Cloud",
            "Diagnose",
            "Speichern & Better GroBro neu starten",
        ):
            assert label in html
        assert "cfg-SOURCE_MQTT_HOST" in html
        assert "cfg-KEEP_BATTERY_POSITION" in html
        assert "api/config" in html
    finally:
        server.shutdown()
        server.server_close()


def test_ingress_page_uses_home_assistant_frontend_language():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert 'localStorage.getItem("selectedLanguage")' in html
        assert "JSON.parse(stored)" in html
        assert "selectedHomeAssistantLanguage()" in html
        assert '["de","en","fr","es","nl"]' in html
        assert '"Übersicht":"Overview"' in html
        assert '"Übersicht":"Vue d\'ensemble"' in html
        assert '"Übersicht":"Resumen"' in html
        assert '"Übersicht":"Overzicht"' in html
        assert '"Speichern & Better GroBro neu starten":"Opslaan en Better GroBro herstarten"' in html
        assert 'nl:{startup:"Starten",started:"Gestart",stopped:"Gestopt",unknown:"Onbekend",error:"Fout"}' in html
        assert 'navigator.language || "en"' in html
        assert "applyLanguage(out.language || selectedHomeAssistantLanguage())" in html
    finally:
        server.shutdown()
        server.server_close()


def test_ingress_page_marks_better_grobro_ui_as_recommended():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert "Empfohlene Konfiguration" in html
        assert "native Konfiguration-Tab bleibt als Fallback verfügbar" in html
    finally:
        server.shutdown()
        server.server_close()


def test_ingress_state_reports_detected_device_families(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clear_device_inventory()
    observe_device("0PVPTEST000001")
    observe_device("QMNTEST0000001")

    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/state",
            timeout=3,
        ) as response:
            state = json.load(response)

        assert [item["display_name"] for item in state["inventory"]] == [
            "NEO",
            "NOAH",
        ]
    finally:
        server.shutdown()
        server.server_close()
        clear_device_inventory()


def test_restart_button_explicitly_names_better_grobro():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert "Speichern & Better GroBro neu starten" in html
        assert "Save & restart Better GroBro" in html
        assert "Enregistrer et redémarrer Better GroBro" in html
        assert "Guardar y reiniciar Better GroBro" in html
        assert "Opslaan en Better GroBro herstarten" in html
        assert "Nur speichern" not in html
        assert "Save only" not in html
        assert "Enregistrer seulement" not in html
        assert "Solo guardar" not in html
        assert "Alleen opslaan" not in html
        assert "saveConfig(false)" not in html
        assert 'host.append(restart);' in html
    finally:
        server.shutdown()
        server.server_close()


def test_log_viewer_preserves_manual_scroll_during_auto_refresh():
    html = battery_ingress._INDEX_HTML

    assert "logFollowTail=true" in html
    assert 'logOutput.addEventListener("scroll"' in html
    assert "logFollowTail=logOutput.scrollHeight-logOutput.scrollTop-logOutput.clientHeight<20" in html
    assert "const currentScrollTop=output.scrollTop" in html
    assert "if(nextText===logLastText)return" in html
    assert "output.scrollTop=output.scrollHeight" in html
    assert "logFollowTail=false" in html
    assert "overflow-y:scroll" in html
    assert "overscroll-behavior:contain" in html


def test_config_save_always_restarts_addon():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert 'body:JSON.stringify({options:collectConfig()})' in html
        assert 'saveConfig(false)' not in html
        assert 'saveConfig(true)' not in html
        assert 'schedule_restart()' not in html
    finally:
        server.shutdown()
        server.server_close()


def test_language_is_applied_only_after_home_assistant_config_load():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        early = "applyLanguage(selectedHomeAssistantLanguage());"
        assert early not in html
        assert "applyLanguage(out.language || selectedHomeAssistantLanguage())" in html
        assert html.index("async function loadConfig()") < html.index(
            "applyLanguage(out.language || selectedHomeAssistantLanguage())"
        )
    finally:
        server.shutdown()
        server.server_close()


def test_battery_assignment_ui_respects_max_bat():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert 'id="row-slot2"' in html
        assert 'id="row-slot3"' in html
        assert 'id="row-slot4"' in html
        assert "function configuredBatteryCount(device)" in html
        assert 'configState.options.MAX_BAT' in html
        assert "return [2,3,4].filter(slot=>slot<=maxBat);" in html
        assert 'row.hidden=!visibleSlots.includes(slot);' in html
        assert "[hidden] { display:none !important; }" in html
    finally:
        server.shutdown()
        server.server_close()


def test_hidden_battery_assignments_are_preserved_when_saving_visible_slots():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert (
            'for(const slot of [2,3,4])assignments[String(slot)]='
            'd.manual[String(slot)]||AUTO;'
        ) in html
        assert (
            'slots.forEach((slot,i)=>assignments[String(slot)]=values[i]);'
        ) in html
    finally:
        server.shutdown()
        server.server_close()


def test_addon_status_is_localized_for_all_supervisor_states():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert 'de:{startup:"Startet",started:"Gestartet",stopped:"Gestoppt",unknown:"Unbekannt",error:"Fehler"}' in html
        assert 'en:{startup:"Starting",started:"Started",stopped:"Stopped",unknown:"Unknown",error:"Error"}' in html
        assert 'fr:{startup:"Démarrage",started:"Démarré",stopped:"Arrêté",unknown:"Inconnu",error:"Erreur"}' in html
        assert 'es:{startup:"Iniciando",started:"Iniciado",stopped:"Detenido",unknown:"Desconocido",error:"Error"}' in html
        assert "summary-state" in html
        assert "localizedAddonState(out.state)" in html
        assert 'summary-state").textContent=out.state' not in html
    finally:
        server.shutdown()
        server.server_close()


def test_sensor_retain_option_is_not_exposed_in_ingress_ui():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert "cfg-PUBLISH_SENSORS_RETAINED" not in html
        assert "Sensorzustände retained" not in html
        assert 'id="cfg-DEVICE_TIMEOUT" type="number" min="1"' in html
    finally:
        server.shutdown()
        server.server_close()


def test_battery_assignment_labels_fixed_master_as_bat1():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert '<label for="device">Bat1 (Master)</label>' in html
        assert '<label for="device">Gerät</label>' not in html
        assert '"Bat1 (Master)":"Bat1 (Master)"' in html
    finally:
        server.shutdown()
        server.server_close()


def test_glitch_filter_option_is_removed_from_ingress_ui():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert "cfg-FILTER_DATA_GLITCHES" not in html
        assert "Messwertsprünge filtern" not in html
        assert "total_increasing unterdrücken" not in html
    finally:
        server.shutdown()
        server.server_close()


def test_battery_settings_are_grouped_on_batteries_page():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        batteries_start = html.index('<section id="tab-batteries"')
        ha_start = html.index('<section id="tab-ha"')
        batteries_html = html[batteries_start:ha_start]
        ha_html = html[ha_start:]

        assert "Batterie-Einstellungen" in batteries_html
        assert 'id="cfg-KEEP_BATTERY_POSITION"' in batteries_html
        assert 'id="cfg-MAX_BAT"' in batteries_html
        assert 'class="actions config-actions"' in batteries_html
        assert 'id="cfg-KEEP_BATTERY_POSITION"' not in ha_html
        assert 'id="cfg-MAX_BAT"' not in ha_html
    finally:
        server.shutdown()
        server.server_close()

def test_ingress_page_contains_current_session_log_viewer():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert 'data-tab="logs"' in html
        assert 'id="tab-logs"' in html
        assert 'id="log-output"' in html
        assert 'id="log-refresh"' in html
        assert 'apiUrl("api/logs")' in html
        assert "setInterval(()=>loadLogs().catch(()=>{}),3000)" in html
        assert "Ältere Supervisor-Protokolle bleiben ausgeblendet." in html
        assert '"Protokoll":"Log"' in html
        assert '"Protokoll":"Journal"' in html
        assert '"Protokoll":"Registro"' in html
        assert '"Protokoll":"Logboek"' in html
    finally:
        server.shutdown()
        server.server_close()


def test_log_viewer_falls_back_to_process_start_when_marker_is_missing(monkeypatch):
    monkeypatch.setattr(
        battery_ingress,
        "get_current_process_logs",
        lambda: {
            "logs": "2026-10-01 00:46:38,100 [INFO] current startup\n"
                    "2026-10-01 00:46:39,100 [INFO] current follow-up",
            "started_at": "2026-10-01T00:46:37+02:00",
            "marker_found": True,
        },
    )

    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/logs",
            timeout=3,
        ) as response:
            result = json.load(response)

        assert result["marker_found"] is True
        assert result["logs"].startswith("2026-10-01 00:46:38,100")
    finally:
        server.shutdown()
        server.server_close()


def test_ingress_logs_api_returns_current_process_only(monkeypatch):
    monkeypatch.setattr(
        battery_ingress,
        "get_current_process_logs",
        lambda: {
            "logs": "2026-09-30 21:31:00 [ERROR] current",
            "started_at": "2026-09-30T21:30:00+02:00",
            "marker_found": True,
        },
    )

    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/logs",
            timeout=3,
        ) as response:
            result = json.load(response)

        assert result["marker_found"] is True
        assert result["logs"].endswith("[ERROR] current")
        assert result["started_at"] == "2026-09-30T21:30:00+02:00"
    finally:
        server.shutdown()
        server.server_close()



def test_log_viewer_preserves_manual_scroll_position():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert 'logOutput.addEventListener("scroll"' in html
        assert (
            "logFollowTail=logOutput.scrollHeight-logOutput.scrollTop-"
            "logOutput.clientHeight<20"
        ) in html
        assert "const currentScrollTop=output.scrollTop;" in html
        assert (
            "output.scrollTop=Math.min(currentScrollTop,"
            "Math.max(0,output.scrollHeight-output.clientHeight));"
        ) in html
        assert "if(followTail){" in html
        assert "output.scrollTop=output.scrollHeight;" in html
    finally:
        server.shutdown()
        server.server_close()
