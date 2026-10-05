from grobro.ha.device_inventory import (
    clear_device_inventory,
    get_device_inventory,
    observe_device,
    observe_telemetry,
    observe_wifi_signal,
)
from grobro.ha.battery_position import prepare_battery_payload, save_manual_assignments
from types import SimpleNamespace
import pytest


def setup_function():
    clear_device_inventory()


def teardown_function():
    clear_device_inventory()


def test_inventory_reports_known_device_families():
    observe_device("0PVPTEST000001")
    observe_device("QMNTEST0000001")
    observe_device("0HVRTEST000001")

    inventory = get_device_inventory()

    assert [(item["display_name"], item["device_id"]) for item in inventory] == [
        ("NEO", "QMNTEST0000001"),
        ("NEXA", "0HVRTEST000001"),
        ("NOAH", "0PVPTEST000001"),
    ]


def test_inventory_updates_existing_device_without_duplicate():
    observe_device("0PVPTEST000001")
    first = get_device_inventory()[0]

    observe_device("0PVPTEST000001")
    inventory = get_device_inventory()

    assert len(inventory) == 1
    assert inventory[0] == first
    assert inventory[0]["display_name"] == "NOAH"


def test_inventory_keeps_unknown_family_visible():
    observe_device("UNKNOWN123")

    inventory = get_device_inventory()

    assert inventory[0]["display_name"] == "UNKNOWN"
    assert inventory[0]["family"] == "unknown"


@pytest.mark.parametrize("invalid", [None, "", "bad", 0, 100, -121])
def test_invalid_wifi_never_replaces_valid_config_or_telemetry(invalid):
    observe_wifi_signal("QMNTEST", -62)
    observe_telemetry("QMNTEST", {"wifi_signal_strength": invalid})
    observe_wifi_signal("QMNTEST", invalid)
    device = get_device_inventory()[0]
    assert device["wifi_signal_strength"] == device["wifi_signal"] == -62


def test_live_wifi_updates_both_aliases_and_snapshots_are_independent():
    observe_wifi_signal("0PVPTEST", " -60 ")
    observe_telemetry("0PVPTEST", {"wifi_signal_strength": -75, "bat_1_soc_pct": 0, "bat1_temp": 0})
    device = get_device_inventory()[0]
    assert device["wifi_signal_strength"] == device["wifi_signal"] == -75
    assert device["batteries"] == [{"slot": 1, "soc": 0, "temperature": 0}]
    device["batteries"][0]["soc"] = 99
    assert get_device_inventory()[0]["batteries"][0]["soc"] == 0


def test_overview_serial_and_measurements_follow_same_manual_mapping(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    device = "0PVPTEST"
    # Explicitly move B into A's physical slot; A must fall back to slot 3.
    save_manual_assignments(device, {"2": "SERIAL_B", "3": "__auto__", "4": "__auto__"})
    payload, count = prepare_battery_payload(SimpleNamespace(), device, {
        "bat2_ser_part_1": "SERIAL_A", "bat3_ser_part_1": "SERIAL_B",
        "bat_2_soc_pct": 20, "bat_3_soc_pct": 80,
        "bat2_temp": 12, "bat3_temp": 24,
    }, use_stable_auto=False)
    observe_telemetry(device, payload, count)
    batteries = get_device_inventory()[0]["batteries"]
    assert batteries[1] == {"slot": 2, "serial": "SERIAL_B", "soc": 80, "temperature": 24}
    assert batteries[2] == {"slot": 3, "serial": "SERIAL_A", "soc": 20, "temperature": 12}
