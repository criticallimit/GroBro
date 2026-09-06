from types import SimpleNamespace

from grobro.ha import client as ha_client
from grobro.ha.performance import (
    _REGISTER_RULES_CACHE,
    _prepare_payload,
    _register_rules,
)
from grobro.model.device_family import DEVICE_FAMILIES


def _reg(
    state_class=None,
    data_type=None,
    device_class=None,
    unit_of_measurement=None,
):
    return SimpleNamespace(
        homeassistant=SimpleNamespace(
            state_class=state_class,
            device_class=device_class,
            unit_of_measurement=unit_of_measurement,
        ),
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


def test_prepare_payload_publishes_power_as_whole_watts(monkeypatch):
    state = SimpleNamespace(
        device_id="0PVPTEST",
        payload={
            "power_zero": -0.4,
            "power_positive": 742.6,
            "power_negative": -1.6,
            "energy_wh": 1234.6,
            "energy_kwh": 12.345,
            "voltage": 230.45,
        },
    )
    known_registers = SimpleNamespace(
        input_registers={
            "power_zero": _reg(device_class="power", unit_of_measurement="W"),
            "power_positive": _reg(device_class="power", unit_of_measurement="W"),
            "power_negative": _reg(device_class="power", unit_of_measurement="W"),
            "energy_wh": _reg(device_class="energy", unit_of_measurement="Wh"),
            "energy_kwh": _reg(device_class="energy", unit_of_measurement="kWh"),
            "voltage": _reg(device_class="voltage", unit_of_measurement="V"),
        }
    )
    client = SimpleNamespace(_last_energy_values={})

    monkeypatch.setattr(ha_client, "FILTER_DATA_GLITCHES", False)
    monkeypatch.setattr(ha_client, "map_enum_value", lambda _reg_def, value: value)

    result = _prepare_payload(
        client,
        state,
        effective_max_bat=4,
        known_registers=known_registers,
    )

    assert result["power_zero"] == 0
    assert result["power_positive"] == 743
    assert result["power_negative"] == -2
    assert result["energy_wh"] == 1234.6
    assert result["energy_kwh"] == 12.345
    assert result["voltage"] == 230.45


def test_whole_watt_rule_covers_every_device_family(monkeypatch):
    """Every supported family must use the same 3.0.1 HA whole-watt path."""
    monkeypatch.setattr(ha_client, "FILTER_DATA_GLITCHES", False)
    monkeypatch.setattr(ha_client, "map_enum_value", lambda _reg_def, value: value)

    for family in DEVICE_FAMILIES:
        power_keys = [
            name
            for name, reg in family.registers.input_registers.items()
            if reg.homeassistant.device_class == "power"
            and reg.homeassistant.unit_of_measurement == "W"
        ]
        assert power_keys, f"{family.key} has no Home Assistant W power entity"

        key = power_keys[0]
        state = SimpleNamespace(
            device_id=f"{family.prefixes[0]}TEST",
            payload={key: -0.4},
        )
        client = SimpleNamespace(_last_energy_values={})

        result = _prepare_payload(
            client,
            state,
            effective_max_bat=4,
            known_registers=family.registers,
        )

        assert result[key] == 0, family.key
        assert key in _register_rules(family.registers)[3], family.key


def test_shared_register_rules_are_cached_for_every_family():
    """Shared HA hot-path rule generation must not be NOAH-only."""
    for family in DEVICE_FAMILIES:
        _REGISTER_RULES_CACHE.pop(id(family.registers), None)
        first = _register_rules(family.registers)
        second = _register_rules(family.registers)
        assert first is second, family.key


def test_register_rules_are_cached_and_preserve_static_semantics():
    known_registers = SimpleNamespace(
        input_registers={
            "bat2_temp": _reg(),
            "bat2_ser_part_1": _reg(),
            "energy": _reg("total_increasing"),
            "enum_value": _reg(data_type="ENUM"),
            "power": _reg(device_class="power", unit_of_measurement="W"),
            "energy_wh": _reg(device_class="energy", unit_of_measurement="Wh"),
        }
    )
    _REGISTER_RULES_CACHE.pop(id(known_registers), None)

    first = _register_rules(known_registers)
    second = _register_rules(known_registers)

    assert first is second
    (
        enum_registers,
        total_increasing,
        invalid_battery_temps,
        whole_watt_power,
        has_serial_parts,
    ) = first
    assert enum_registers["enum_value"] is known_registers.input_registers["enum_value"]
    assert total_increasing == frozenset({"energy"})
    assert invalid_battery_temps == frozenset({"bat2_temp"})
    assert whole_watt_power == frozenset({"power"})
    assert has_serial_parts is True
