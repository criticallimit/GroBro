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
import json
from unittest.mock import patch
from grobro import ha, model


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


@pytest.mark.parametrize("temperature", [-273.1, 0, 21.5])
def test_overview_uses_the_same_temperature_validation_as_ha(tmp_path, monkeypatch, temperature):
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client"):
        target = ha.Client(model.MQTTConfig(host="localhost", port=1883))
        target._ha_mqtt_connected = True  # Simulate Paho CONNACK for runtime tests
    target._client.publish.return_value = (0, None)
    try:
        target.publish_input_register(SimpleNamespace(
            device_id="0PVPTEST", payload={"bat1_temp": temperature, "bat_1_soc_pct": 50},
        ))
        published = [call.args[1] for call in target._client.publish.call_args_list
                     if call.args[0] == "homeassistant/grobro/0PVPTEST/state"]
        expected = None if temperature == -273.1 else temperature
        assert json.loads(published[-1])["bat1_temp"] == expected
        assert get_device_inventory()[0]["batteries"][0].get("temperature") == expected
    finally:
        target.stop()

def test_restored_device_is_not_considered_online_without_live_telemetry():
    observe_device("QMNTEST0000001")
    observe_wifi_signal("QMNTEST0000001", -59)
    item = get_device_inventory()[0]
    assert item["connection_status"] == "unknown"
    assert item["last_activity_seconds"] is None


def test_existing_availability_events_drive_ingress_status():
    from grobro.ha.device_inventory import observe_device_activity, observe_device_availability

    observe_device("QMNTEST0000001")
    with patch("grobro.ha.device_inventory.time.monotonic", return_value=1000.0):
        observe_device_activity("QMNTEST0000001")
    with patch("grobro.ha.device_inventory.time.monotonic", return_value=1010.0):
        item = get_device_inventory()[0]
    # Receiving telemetry alone is not proof that publishing HA availability succeeded.
    assert item["connection_status"] == "unknown"
    assert item["last_activity_seconds"] == 10
    observe_device_availability("QMNTEST0000001", True)
    assert get_device_inventory()[0]["connection_status"] == "online"
    observe_device_availability("QMNTEST0000001", False)
    assert get_device_inventory()[0]["connection_status"] == "offline"


def test_wifi_and_cached_telemetry_do_not_override_existing_offline_status():
    from grobro.ha.device_inventory import observe_device_activity, observe_device_availability

    device = "QMNTEST0000001"
    observe_device_activity(device)
    observe_device_availability(device, False)
    observe_device(device)
    observe_wifi_signal(device, -58)
    observe_telemetry(device, {"bat_1_soc_pct": 21})
    assert get_device_inventory()[0]["connection_status"] == "offline"
    observe_device_activity(device)
    assert get_device_inventory()[0]["connection_status"] == "offline"
    observe_device_availability(device, True)
    assert get_device_inventory()[0]["connection_status"] == "online"


@pytest.mark.parametrize("device", [
    "0PVPTEST000001", "QMNTEST0000001", "0HVRTEST000001",
])
def test_all_families_use_same_existing_ha_availability(device):
    from grobro.ha.device_inventory import observe_device_activity, observe_device_availability

    observe_device(device)
    assert get_device_inventory()[0]["connection_status"] == "unknown"
    observe_device_activity(device)
    assert get_device_inventory()[0]["connection_status"] == "unknown"
    observe_device_availability(device, True)
    assert get_device_inventory()[0]["connection_status"] == "online"
    observe_device_availability(device, False)
    assert get_device_inventory()[0]["connection_status"] == "offline"
    observe_device_activity(device)
    observe_device_availability(device, True)
    assert get_device_inventory()[0]["connection_status"] == "online"


def test_ha_mqtt_availability_success_is_mirrored_in_overview():
    with patch("paho.mqtt.client.Client"):
        target = ha.Client(model.MQTTConfig(host="localhost", port=1883))
        target._ha_mqtt_connected = True  # Simulate Paho CONNACK for runtime tests
    try:
        target._client.publish.return_value = (0, None)
        target._Client__publish_availability("QMNTEST0000001", True)
        assert get_device_inventory()[0]["connection_status"] == "online"
        target._Client__publish_availability("QMNTEST0000001", False)
        assert get_device_inventory()[0]["connection_status"] == "offline"
    finally:
        target.stop()


def test_ha_mqtt_availability_rejection_does_not_mark_device_online():
    with patch("paho.mqtt.client.Client"):
        target = ha.Client(model.MQTTConfig(host="localhost", port=1883))
        target._ha_mqtt_connected = True  # Simulate Paho CONNACK for runtime tests
    try:
        observe_device("QMNTEST0000001")
        target._client.publish.return_value = (1, None)
        target._Client__publish_availability("QMNTEST0000001", True)
        assert get_device_inventory()[0]["connection_status"] == "unknown"
    finally:
        target.stop()


def test_bridge_disconnect_marks_all_families_offline_without_erasing_inventory():
    from grobro.ha.device_inventory import observe_device_availability, mark_all_devices_offline

    devices = ("0PVPTEST000001", "QMNTEST0000001", "0HVRTEST000001")
    for device in devices:
        observe_device_availability(device, True)
    mark_all_devices_offline()
    snapshot = get_device_inventory()
    assert {item["device_id"] for item in snapshot} == set(devices)
    assert all(item["connection_status"] == "offline" for item in snapshot)
    observe_device_availability("QMNTEST0000001", True)
    assert next(item for item in get_device_inventory() if item["family"] == "neo")["connection_status"] == "online"


def test_ha_mqtt_disconnection_clears_overview_online_status():
    from grobro.ha.device_inventory import observe_device_availability

    with patch("paho.mqtt.client.Client"):
        target = ha.Client(model.MQTTConfig(host="localhost", port=1883))
        target._ha_mqtt_connected = True  # Simulate Paho CONNACK for runtime tests
    try:
        observe_device_availability("QMNTEST0000001", True)
        target._Client__on_disconnect(target._client, None, None, None, None)
        assert get_device_inventory()[0]["connection_status"] == "offline"
        assert target._bridge_online_pending is True
    finally:
        target.stop()


def test_offline_ha_mqtt_queue_does_not_falsely_restore_online_card():
    from grobro.ha.device_inventory import observe_device_availability
    from types import SimpleNamespace

    with patch("paho.mqtt.client.Client"):
        target = ha.Client(model.MQTTConfig(host="localhost", port=1883))
        target._ha_mqtt_connected = True  # Simulate Paho CONNACK for runtime tests
    try:
        device = "QMNTEST0000001"
        target._client.publish.return_value = (0, None)
        observe_device_availability(device, True)
        target._Client__on_disconnect(target._client, None, None, None, None)
        assert get_device_inventory()[0]["connection_status"] == "offline"
        target._client.publish.reset_mock()
        # Paho may report a queued publish as accepted while not connected.
        assert target._Client__publish_availability(device, True) is False
        assert get_device_inventory()[0]["connection_status"] == "offline"
        target._client.publish.assert_not_called()

        # Simulate a broker reconnect; subsequent availability can be emitted.
        target._ha_mqtt_connected = True
        target._last_availability.clear()
        assert target._Client__publish_availability(device, True) is True
        assert get_device_inventory()[0]["connection_status"] == "online"
    finally:
        target.stop()
