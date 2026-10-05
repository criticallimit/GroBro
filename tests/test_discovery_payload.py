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
