"""Discovery definitions can be built independently of clients and I/O."""
from grobro.ha.discovery_payload import build_discovery_payload
from grobro.model.device_family import DEVICE_FAMILIES

import pytest


@pytest.mark.parametrize("family", DEVICE_FAMILIES, ids=lambda family: family.key)
def test_discovery_builder_preserves_definitions_and_entity_identity(family):
    device = family.prefixes[0] + "TEST"
    definitions = family.registers.model_dump()
    metadata = {"identifiers": [device], "manufacturer": "Growatt"}
    options = dict(
        base_topic="ha-test", bridge_topic="ha-test/bridge/availability",
        effective_max_bat=4, pv_count=4, max_slots=3,
        device_timeout=120, availability_sensor=True,
    )
    first = build_discovery_payload(device, family.registers, metadata, **options)
    assert family.registers.model_dump() == definitions
    assert metadata == {"identifiers": [device], "manufacturer": "Growatt"}
    assert first["availability"] == [
        {"topic": f"ha-test/grobro/{device}/availability"},
        {"topic": "ha-test/bridge/availability"},
    ]
    assert first["availability_mode"] == "all"
    assert first["cmps"][f"grobro_{device}_serial"]["state_topic"] == f"ha-test/grobro/{device}/serial"
    assert first["cmps"][f"grobro_{device}_restart_datalogger"]["command_topic"] == f"ha-test/config/grobro/{device}/32/set"
    redundant_default_icons = {
        ("battery", "mdi:battery"),
        ("temperature", "mdi:thermometer"),
        ("current", "mdi:current-ac"),
        ("frequency", "mdi:sine-wave"),
        ("signal_strength", "mdi:wifi"),
        ("voltage", "mdi:flash"),
        ("voltage", "mdi:sine-wave"),
        ("power", "mdi:flash"),
    }
    for component in first["cmps"].values():
        assert (
            component.get("device_class"),
            component.get("icon"),
        ) not in redundant_default_icons

    # Semantic icons must remain explicit instead of being stripped globally.
    configured_semantic_icons = {
        register.homeassistant.icon
        for register in family.registers.input_registers.values()
        if register.homeassistant.publish
        and register.homeassistant.icon in {
            "mdi:solar-power",
            "mdi:power-plug",
            "mdi:battery-sync",
            "mdi:flash-triangle",
        }
    }
    discovered_icons = {
        component.get("icon") for component in first["cmps"].values()
    }
    assert configured_semantic_icons <= discovered_icons
    assert all(key == component["unique_id"] for key, component in first["cmps"].items())
    first["cmps"].clear()
    second = build_discovery_payload(device, family.registers, metadata, **options)
    assert second["cmps"]
    assert family.registers.model_dump() == definitions



@pytest.mark.parametrize("family_key", ["noah", "nexa"])
def test_slot_mode_select_is_optimistic_but_keeps_hardware_state_topic(family_key):
    family = next(f for f in DEVICE_FAMILIES if f.key == family_key)
    serial = family.prefixes[0] + "TEST"
    components = build_discovery_payload(
        serial, family.registers,
        {"identifiers": [serial], "manufacturer": "Growatt"},
        base_topic="ha-test", bridge_topic="ha-test/bridge/availability",
        effective_max_bat=4, pv_count=4, max_slots=3,
        device_timeout=120, availability_sensor=True,
    )["cmps"]
    entity = components[f"grobro_{serial}_cmd_slot1_mode"]
    assert entity["platform"] == "select"
    assert entity["optimistic"] is True
    assert entity["state_topic"] == f"ha-test/select/grobro/{serial}/slot1_mode/get"
    assert entity["command_topic"] == f"ha-test/select/grobro/{serial}/slot1_mode/set"
    assert entity["options"] == ["Load First", "Battery First", "Smart Mode"]
    power = components[f"grobro_{serial}_cmd_slot1_power"]
    assert power["platform"] == "number"
    assert power["optimistic"] is True
    assert power["state_topic"] == f"ha-test/number/grobro/{serial}/slot1_power/get"
    assert power["command_topic"] == f"ha-test/number/grobro/{serial}/slot1_power/set"
    enabled = components[f"grobro_{serial}_cmd_slot1_enabled"]
    assert enabled["platform"] == "switch"
    assert enabled["optimistic"] is True
    assert enabled["state_topic"] == f"ha-test/switch/grobro/{serial}/slot1_enabled/get"
    assert enabled["command_topic"] == f"ha-test/switch/grobro/{serial}/slot1_enabled/set"
    time = components[f"grobro_{serial}_cmd_slot1_start_time"]
    assert "optimistic" not in time


def test_neo_inverter_switch_uses_bridge_availability_only():
    family = next(f for f in DEVICE_FAMILIES if f.key == "neo")
    serial = family.prefixes[0] + "TEST"
    payload = build_discovery_payload(
        serial, family.registers,
        {"identifiers": [serial], "manufacturer": "Growatt"},
        base_topic="ha-test", bridge_topic="ha-test/bridge/availability",
        effective_max_bat=4, pv_count=4, max_slots=3,
        device_timeout=120, availability_sensor=True,
    )
    switch = payload["cmps"][f"grobro_{serial}_cmd_inverter_power"]
    assert switch["platform"] == "switch"
    assert switch["availability"] == [{"topic": "ha-test/bridge/availability"}]
    assert switch["state_topic"] == f"ha-test/switch/grobro/{serial}/inverter_power/get"
    assert switch["command_topic"] == f"ha-test/switch/grobro/{serial}/inverter_power/set"
    assert payload["availability"] == [
        {"topic": f"ha-test/grobro/{serial}/availability"},
        {"topic": "ha-test/bridge/availability"},
    ]
    other = payload["cmps"][f"grobro_{serial}_cmd_output_power_limit"]
    assert "availability" not in other


@pytest.mark.parametrize("family_key", ["neo", "noah", "nexa"])
def test_common_config_entities_keep_identical_register_topics(family_key):
    family = next(f for f in DEVICE_FAMILIES if f.key == family_key)
    serial = family.prefixes[0] + "TEST"
    components = build_discovery_payload(
        serial, family.registers,
        {"identifiers": [serial], "manufacturer": "Growatt"},
        base_topic="ha-test", bridge_topic="ha-test/bridge/availability",
        effective_max_bat=4, pv_count=4, max_slots=3,
        device_timeout=120, availability_sensor=True,
    )["cmps"]

    for key, register_no, platform in (
        ("data_interval", 4, "number"),
        ("wifi_signal_strength", 76, "sensor"),
    ):
        config = family.registers.config_registers[key]
        assert config.growatt.register_no == register_no
        uid = f"grobro_{serial}_cmd_{key}"
        component = components[uid]
        assert component["platform"] == platform
        assert component["state_topic"] == f"ha-test/config/grobro/{serial}/{register_no}/get"
        if platform != "sensor":
            assert component["command_topic"] == f"ha-test/config/grobro/{serial}/{register_no}/set"
        else:
            assert "command_topic" not in component
