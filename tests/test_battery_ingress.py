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


def test_ingress_page_has_back_navigation_and_auto_return():
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode()

        assert 'id="back-top"' in html
        assert 'id="back-bottom"' in html
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
                "restart": True,
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
        assert '["de","en","fr","es"]' in html
        assert '"Übersicht":"Overview"' in html
        assert '"Übersicht":"Vue d\'ensemble"' in html
        assert '"Übersicht":"Resumen"' in html
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
