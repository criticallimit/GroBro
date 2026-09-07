from types import SimpleNamespace

from grobro.ha.client import iter_command_registers
from grobro.ha.discovery_runtime import clean_discovery_payload
from grobro.model.growatt_registers import (
    KNOWN_NEO_REGISTERS,
    KNOWN_NEXA_REGISTERS,
    KNOWN_NOAH_REGISTERS,
)


def test_mqtt_ip_hidden_for_noah_neo_and_nexa():
    for registers in (
        KNOWN_NOAH_REGISTERS,
        KNOWN_NEO_REGISTERS,
        KNOWN_NEXA_REGISTERS,
    ):
        assert "mqtt_ip" not in registers.config_registers


def test_noah_only_experimental_temperature_removals_stay_noah_only():
    for name in ("pv1Temp", "pv2Temp", "systemTemp"):
        assert name not in KNOWN_NOAH_REGISTERS.input_registers


def test_neo_inverter_power_remains_a_published_switch_command():
    inverter_power = KNOWN_NEO_REGISTERS.holding_registers["inverter_power"]
    assert inverter_power.homeassistant.publish is True
    assert inverter_power.homeassistant.type == "switch"
    assert inverter_power.homeassistant.name == "Inverter Power"

    command_names = {
        entry["name"]
        for entry in iter_command_registers(KNOWN_NEO_REGISTERS)
        if entry["ha"].publish
    }
    assert "inverter_power" in command_names


def test_shared_discovery_cleanup_keeps_upstream_neo_inverter_power_and_hides_manual_time():
    device_id = "QMNTEST"
    client = SimpleNamespace(_config_cache={})
    data = {
        "cmps": {
            f"grobro_{device_id}_cmd_inverter_power": {
                "platform": "switch",
                "name": "Inverter Power",
                "command_topic": f"homeassistant/switch/grobro/{device_id}/inverter_power/set",
                "state_topic": f"homeassistant/switch/grobro/{device_id}/inverter_power/get",
                "publish": True,
                "type": "switch",
            },
            f"grobro_{device_id}_sync_time": {
                "platform": "button",
                "name": "Sync Time",
            },
            f"grobro_{device_id}_cmd_system_time": {
                "platform": "text",
                "name": "System Time",
            },
        }
    }

    cleaned = clean_discovery_payload(client, device_id, data)
    components = cleaned["cmps"]

    inverter = components[f"grobro_{device_id}_cmd_inverter_power"]
    assert inverter["platform"] == "switch"
    assert inverter["name"] == "Inverter Power"
    assert inverter["command_topic"].endswith("/inverter_power/set")
    assert inverter["state_topic"].endswith("/inverter_power/get")
    assert inverter["publish"] is True
    assert inverter["type"] == "switch"

    assert f"grobro_{device_id}_sync_time" not in components
    assert f"grobro_{device_id}_cmd_system_time" not in components
