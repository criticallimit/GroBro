"""Regression checks for battery capacity and NEO protocol recovery."""
import struct

import pytest
from paho.mqtt.client import MQTTMessage
from unittest.mock import MagicMock, patch

from grobro.grobro.builder import scramble
from grobro.grobro.client import Client as GrowattClient
from grobro.ha.battery_capacity import nominal_battery_capacity
from grobro.ha.discovery_payload import build_discovery_payload
from grobro.model.device_family import get_known_registers
from grobro.model.mqtt_config import MQTTConfig


@pytest.mark.parametrize("device,payload,expected", [
    ("0PVP0000TEST0001", {"bat_cnt": 1}, 2.048),
    ("0PVP0000TEST0001", {"bat_cnt": 3}, 6.144),
    ("0PVP0000TEST0001", {"bat_cnt": 4}, 8.192),
    ("0HVR0000TEST0001", {"batteryPackageQuantity": 2}, 4.096),
    ("QMN000ABC1D2E3FG", {"bat_cnt": 4}, None),
    ("0PVP0000TEST0001", {}, None),
    ("0PVP0000TEST0001", {"bat_cnt": 0}, None),
    ("0PVP0000TEST0001", {"bat_cnt": 5}, None),
    ("0PVP0000TEST0001", {"bat_cnt": "3"}, None),
])
def test_nominal_total_capacity_only_when_pack_count_is_confirmed(device, payload, expected):
    assert nominal_battery_capacity(device, payload) == expected


def test_capacity_discovery_has_stable_identifier():
    device = "0PVP0000TEST0001"
    payload = build_discovery_payload(
        device, get_known_registers(device), {"identifiers": [device]},
        base_topic="homeassistant", bridge_topic="homeassistant/grobro/bridge/availability",
        effective_max_bat=4, pv_count=None, max_slots=1,
        device_timeout=120, availability_sensor=False,
    )
    sensor = payload["cmps"][f"grobro_{device}_battery_total_capacity_kwh"]
    assert sensor["unit_of_measurement"] == "kWh"
    assert sensor["state_class"] == "measurement"
    assert "battery_total_capacity_kwh" in sensor["value_template"]


@pytest.fixture
def gateway():
    with patch("grobro.grobro.client.mqtt.Client"):
        client = GrowattClient(MQTTConfig(host="localhost", port=1883), None)
        client.on_config = MagicMock()
        client.on_input_register = MagicMock()
        client.on_holding_register_input = MagicMock()
        client.on_config_read_response = MagicMock()
        yield client


def _modbus_msg(function, data):
    device = b"QMN000ABC1D2E3FG".ljust(30, bytes([0]))
    payload = struct.pack(">HHHBB30s", 1, 7, 30 + len(data), 1, function, device) + data + bytes([0, 0])
    # msg_len must be length of entire frame minus its 8-byte prefix.
    payload = bytearray(payload)
    struct.pack_into(">H", payload, 4, len(payload) - 8)
    msg = MagicMock(spec=MQTTMessage)
    msg.topic = "c/33/QMN000ABC1D2E3FG"
    msg.payload = scramble(bytes(payload))
    msg.properties.json.return_value = {"UserProperty": []}
    return msg


def test_neo_confirmed_write_ack_updates_limit(gateway):
    gateway._client.on_message(None, None, _modbus_msg(6, struct.pack(">HBH", 3, 0, 74)))
    state = gateway.on_holding_register_input.call_args.args[0]
    assert state.payload[0].name == "output_power_limit"
    assert state.payload[0].value == 74


def test_neo_write_ack_rejects_failed_status(gateway):
    gateway._client.on_message(None, None, _modbus_msg(6, struct.pack(">HBH", 3, 1, 74)))
    gateway.on_holding_register_input.assert_not_called()


def test_neo_holding_block_uses_raw_one_as_full_limit(gateway):
    gateway._client.on_message(None, None, _modbus_msg(3, struct.pack(">HHH", 3, 3, 1)))
    state = gateway.on_holding_register_input.call_args.args[0]
    assert state.payload[0].name == "output_power_limit"
    assert state.payload[0].value == 100


def test_cached_measurements_have_timestamps_and_ha_attributes(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from grobro.ha.sensor_cache import merge_state

    monkeypatch.setenv("BETTER_GROBRO_STATE_DIR", str(tmp_path))
    device = "0PVP0000TEST0001"
    registers = get_known_registers(device)
    client = SimpleNamespace()
    merge_state(client, device, {"bat2_temp": 23.5}, registers,
                detected_bat_count=2, max_bat=2)
    latest = merge_state(client, device, {"bat2_temp": 0}, registers,
                         detected_bat_count=1, max_bat=2)
    assert latest["bat2_temp"] == 23.5
    meta = latest["battery_cached_values"]["bat2_temp"]
    assert meta["observed_at"] > 0
    assert meta["age_minutes"] >= 0

    discovery = build_discovery_payload(
        device, registers, {"identifiers": [device]},
        base_topic="homeassistant", bridge_topic="homeassistant/grobro/bridge/availability",
        effective_max_bat=2, pv_count=None, max_slots=1, device_timeout=120,
        availability_sensor=False,
    )
    attributes = discovery["cmps"][f"grobro_{device}_bat2_temp"]["json_attributes_template"]
    assert "last_live_at" in attributes
    assert "cached" in attributes
