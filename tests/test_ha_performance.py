from types import SimpleNamespace

from grobro.ha import client as ha_client
from grobro.ha.performance import (
    _REGISTER_RULES_CACHE,
    _prepare_payload,
    _register_rules,
)


def _reg(state_class=None, data_type=None):
    return SimpleNamespace(
        homeassistant=SimpleNamespace(state_class=state_class),
        growatt=SimpleNamespace(
            data=SimpleNamespace(data_type=data_type) if data_type is not None else None
        ),
    )


def test_prepare_payload_preserves_existing_value_rules(monkeypatch):
    state = SimpleNamespace(
        device_id="0PVPTEST",
        payload={
            "bat2_temp": -273.1,
            "bat4_soc": 77,
            "energy": 100,
            "enum_value": 1,
            "plain": 5,
        },
    )
    known_registers = SimpleNamespace(
        input_registers={
            "bat2_temp": _reg(),
            "bat4_soc": _reg(),
            "energy": _reg("total_increasing"),
            "enum_value": _reg(data_type="ENUM"),
            "plain": _reg(),
        }
    )
    client = SimpleNamespace(
        _last_energy_values={(state.device_id, "energy"): 120},
    )

    monkeypatch.setattr(ha_client, "FILTER_DATA_GLITCHES", True)
    monkeypatch.setattr(
        ha_client,
        "map_enum_value",
        lambda _reg_def, value: "Mapped" if value == 1 else value,
    )

    result = _prepare_payload(
        client,
        state,
        effective_max_bat=3,
        known_registers=known_registers,
    )

    assert result == {
        "bat2_temp": None,
        "energy": 120,
        "enum_value": "Mapped",
        "plain": 5,
    }
    assert state.payload["bat2_temp"] == -273.1
    assert state.payload["bat4_soc"] == 77


def test_prepare_payload_updates_increasing_energy_cache(monkeypatch):
    state = SimpleNamespace(
        device_id="QMNTEST",
        payload={"energy": 125},
    )
    known_registers = SimpleNamespace(
        input_registers={"energy": _reg("total_increasing")},
    )
    client = SimpleNamespace(
        _last_energy_values={(state.device_id, "energy"): 120},
    )

    monkeypatch.setattr(ha_client, "FILTER_DATA_GLITCHES", True)
    monkeypatch.setattr(ha_client, "map_enum_value", lambda _reg_def, value: value)

    result = _prepare_payload(
        client,
        state,
        effective_max_bat=4,
        known_registers=known_registers,
    )

    assert result["energy"] == 125
    assert client._last_energy_values[(state.device_id, "energy")] == 125


def test_register_rules_are_cached_and_preserve_static_semantics():
    known_registers = SimpleNamespace(
        input_registers={
            "bat2_temp": _reg(),
            "bat2_ser_part_1": _reg(),
            "energy": _reg("total_increasing"),
            "enum_value": _reg(data_type="ENUM"),
        }
    )
    _REGISTER_RULES_CACHE.pop(id(known_registers), None)

    first = _register_rules(known_registers)
    second = _register_rules(known_registers)

    assert first is second
    enum_registers, total_increasing, invalid_battery_temps, has_serial_parts = first
    assert enum_registers["enum_value"] is known_registers.input_registers["enum_value"]
    assert total_increasing == frozenset({"energy"})
    assert invalid_battery_temps == frozenset({"bat2_temp"})
    assert has_serial_parts is True
