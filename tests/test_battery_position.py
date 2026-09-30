from types import SimpleNamespace

from grobro.ha.battery_position import (
    AUTO_ASSIGNMENT,
    EMPTY_ASSIGNMENT,
    load_battery_ui_state,
    observe_battery_serials,
    save_manual_assignments,
    stabilize_battery_payload,
)
from grobro.model.growatt_registers import KNOWN_NEXA_REGISTERS


def _payload(slot2_serial=None, slot3_serial=None, slot4_serial=None, **values):
    payload = dict(values)
    for slot, serial in ((2, slot2_serial), (3, slot3_serial), (4, slot4_serial)):
        if serial:
            payload[f"bat{slot}_ser_part_1"] = serial
    return payload


def test_first_observation_persists_current_battery_slots(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = SimpleNamespace()

    payload = _payload(
        slot2_serial="SN00200000000001",
        slot3_serial="SN00300000000002",
        bat2_temp=22.0,
        bat3_temp=23.0,
    )
    remapped, logical_max = stabilize_battery_payload(client, "0PVPTEST", payload)

    assert remapped == payload
    assert logical_max == 3
    assert client._battery_position_maps["0PVPTEST"] == {
        "SN00200000000001": 2,
        "SN00300000000002": 3,
    }
    assert (tmp_path / "battery_positions.json").exists()


def test_bat3_does_not_become_bat2_when_bat2_disappears(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = SimpleNamespace()

    stabilize_battery_payload(
        client,
        "0PVPTEST",
        _payload(
            slot2_serial="SN00200000000001",
            slot3_serial="SN00300000000002",
            bat2_temp=22.0,
            bat3_temp=23.0,
        ),
    )

    remapped, logical_max = stabilize_battery_payload(
        client,
        "0PVPTEST",
        _payload(
            slot2_serial="SN00300000000002",
            bat2_temp=31.5,
        ),
    )

    assert logical_max == 3
    assert "bat2_temp" not in remapped
    assert remapped["bat3_temp"] == 31.5
    assert "bat2_ser_part_1" not in remapped
    assert remapped["bat3_ser_part_1"] == "SN00300000000002"


def test_battery_returns_to_its_original_slot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = SimpleNamespace()

    stabilize_battery_payload(
        client,
        "0PVPTEST",
        _payload(slot2_serial="SN00200000000001", slot3_serial="SN00300000000002"),
    )
    stabilize_battery_payload(
        client,
        "0PVPTEST",
        _payload(slot2_serial="SN00300000000002", bat2_temp=30.0),
    )

    remapped, logical_max = stabilize_battery_payload(
        client,
        "0PVPTEST",
        _payload(
            slot2_serial="SN00200000000001",
            slot3_serial="SN00300000000002",
            bat2_temp=24.0,
            bat3_temp=25.0,
        ),
    )

    assert logical_max == 3
    assert remapped["bat2_temp"] == 24.0
    assert remapped["bat3_temp"] == 25.0


def test_persisted_mapping_survives_client_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    first_client = SimpleNamespace()
    stabilize_battery_payload(
        first_client,
        "0PVPTEST",
        _payload(slot2_serial="SN00200000000001", slot3_serial="SN00300000000002"),
    )

    restarted_client = SimpleNamespace()
    remapped, logical_max = stabilize_battery_payload(
        restarted_client,
        "0PVPTEST",
        _payload(slot2_serial="SN00300000000002", bat2_temp=28.0),
    )

    assert logical_max == 3
    assert remapped["bat3_temp"] == 28.0
    assert restarted_client._battery_position_maps["0PVPTEST"]["SN00300000000002"] == 3


def test_unknown_new_battery_cannot_steal_reserved_slot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = SimpleNamespace()

    stabilize_battery_payload(
        client,
        "0PVPTEST",
        _payload(slot2_serial="SN00200000000001", slot3_serial="SN00300000000002"),
    )

    remapped, logical_max = stabilize_battery_payload(
        client,
        "0PVPTEST",
        _payload(slot2_serial="SNNEW00000000003", bat2_temp=26.0),
    )

    assert logical_max == 4
    assert remapped["bat4_temp"] == 26.0
    assert client._battery_position_maps["0PVPTEST"]["SNNEW00000000003"] == 4


def test_nexa_slot_specific_values_follow_their_battery(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = SimpleNamespace()

    stabilize_battery_payload(
        client,
        "0HVRTEST",
        _payload(
            slot2_serial="NXBAT20000000001",
            slot3_serial="NXBAT30000000002",
            battery2Soc=72,
            battery3Soc=83,
        ),
    )

    remapped, logical_max = stabilize_battery_payload(
        client,
        "0HVRTEST",
        _payload(
            slot2_serial="NXBAT30000000002",
            battery2Soc=81,
        ),
    )

    assert logical_max == 3
    assert "battery2Soc" not in remapped
    assert remapped["battery3Soc"] == 81
    assert "bat2_ser_part_1" not in remapped
    assert remapped["bat3_ser_part_1"] == "NXBAT30000000002"


def test_invalid_serial_fragments_never_create_slot_mapping(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = SimpleNamespace()

    payload = _payload(
        slot2_serial="\x01BAD",
        battery2Soc=50,
    )
    remapped, logical_max = stabilize_battery_payload(client, "0HVRTEST", payload)

    assert remapped == payload
    assert logical_max == 1
    assert client._battery_position_maps.get("0HVRTEST", {}) == {}


def test_nexa_module_serial_registers_are_internal_only():
    expected = {
        "bat2_ser_part_1": 33,
        "bat2_ser_part_2": 35,
        "bat2_ser_part_3": 37,
        "bat2_ser_part_4": 39,
        "bat3_ser_part_1": 45,
        "bat3_ser_part_2": 47,
        "bat3_ser_part_3": 49,
        "bat3_ser_part_4": 51,
        "bat4_ser_part_1": 57,
        "bat4_ser_part_2": 59,
        "bat4_ser_part_3": 61,
        "bat4_ser_part_4": 63,
    }

    for name, register_no in expected.items():
        register = KNOWN_NEXA_REGISTERS.input_registers[name]
        assert register.growatt.position.register_no == register_no
        assert register.homeassistant.publish is False


def test_manual_serial_assignment_overrides_automatic_slot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_manual_assignments(
        "0PVPTEST",
        {
            "2": "SN00300000000002",
            "3": "SN00200000000001",
            "4": AUTO_ASSIGNMENT,
        },
    )
    client = SimpleNamespace()
    payload = _payload(
        slot2_serial="SN00200000000001",
        slot3_serial="SN00300000000002",
        bat2_temp=22.0,
        bat3_temp=23.0,
    )

    remapped, logical_max = stabilize_battery_payload(
        client,
        "0PVPTEST",
        payload,
        use_stable_auto=False,
    )

    assert logical_max == 3
    assert remapped["bat2_temp"] == 23.0
    assert remapped["bat3_temp"] == 22.0


def test_manual_empty_slot_is_reserved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_manual_assignments(
        "0PVPTEST",
        {
            "2": EMPTY_ASSIGNMENT,
            "3": AUTO_ASSIGNMENT,
            "4": AUTO_ASSIGNMENT,
        },
    )
    client = SimpleNamespace()

    remapped, logical_max = stabilize_battery_payload(
        client,
        "0PVPTEST",
        _payload(slot2_serial="SN00200000000001", bat2_temp=26.0),
        use_stable_auto=False,
    )

    assert "bat2_temp" not in remapped
    assert remapped["bat3_temp"] == 26.0
    assert logical_max == 3


def test_duplicate_manual_serial_assignment_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    try:
        save_manual_assignments(
            "0PVPTEST",
            {
                "2": "SN00200000000001",
                "3": "SN00200000000001",
                "4": AUTO_ASSIGNMENT,
            },
        )
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate serial assignment was accepted")


def test_detected_serials_are_exposed_to_ingress_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KEEP_BATTERY_POSITION", "true")
    client = SimpleNamespace()

    observe_battery_serials(
        client,
        "0HVRTEST",
        _payload(
            slot2_serial="NXBAT20000000001",
            slot3_serial="NXBAT30000000002",
        ),
    )
    state = load_battery_ui_state()

    assert state["keep_battery_position"] is True
    device = state["devices"][0]
    assert device["device_id"] == "0HVRTEST"
    assert device["detected"] == [
        {"physical_slot": 2, "serial": "NXBAT20000000001"},
        {"physical_slot": 3, "serial": "NXBAT30000000002"},
    ]


def test_manual_assignment_moves_all_noah_slot_values_with_serial(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_manual_assignments(
        "0PVPTEST",
        {
            "2": "SN00300000000002",
            "3": "SN00200000000001",
            "4": AUTO_ASSIGNMENT,
        },
    )
    client = SimpleNamespace()
    payload = _payload(
        slot2_serial="SN00200000000001",
        slot3_serial="SN00300000000002",
        bat2_temp=22.5,
        bat3_temp=31.0,
        bat_2_soc_pct=41,
        bat_3_soc_pct=86,
    )

    remapped, logical_max = stabilize_battery_payload(
        client,
        "0PVPTEST",
        payload,
        use_stable_auto=False,
    )

    assert logical_max == 3
    assert remapped["bat2_temp"] == 31.0
    assert remapped["bat3_temp"] == 22.5
    assert remapped["bat_2_soc_pct"] == 86
    assert remapped["bat_3_soc_pct"] == 41
    assert remapped["bat2_ser_part_1"] == "SN00300000000002"
    assert remapped["bat3_ser_part_1"] == "SN00200000000001"


def test_manual_assignment_moves_all_nexa_slot_values_with_serial(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_manual_assignments(
        "0HVRTEST",
        {
            "2": "NXBAT30000000002",
            "3": "NXBAT20000000001",
            "4": AUTO_ASSIGNMENT,
        },
    )
    client = SimpleNamespace()
    payload = _payload(
        slot2_serial="NXBAT20000000001",
        slot3_serial="NXBAT30000000002",
        battery2Soc=52,
        battery3Soc=91,
    )

    remapped, logical_max = stabilize_battery_payload(
        client,
        "0HVRTEST",
        payload,
        use_stable_auto=False,
    )

    assert logical_max == 3
    assert remapped["battery2Soc"] == 91
    assert remapped["battery3Soc"] == 52
    assert remapped["bat2_ser_part_1"] == "NXBAT30000000002"
    assert remapped["bat3_ser_part_1"] == "NXBAT20000000001"


def test_all_current_slot_specific_noah_and_nexa_register_names_are_remappable():
    from grobro.ha.battery_position import _logical_slot_from_key

    current_slot_registers = {
        "bat2_temp": 2,
        "bat3_temp": 3,
        "bat4_temp": 4,
        "bat_2_soc_pct": 2,
        "bat_3_soc_pct": 3,
        "bat_4_soc_pct": 4,
        "battery2Soc": 2,
        "battery3Soc": 3,
        "battery4Soc": 4,
        "bat2_ser_part_1": 2,
        "bat3_ser_part_1": 3,
        "bat4_ser_part_1": 4,
    }

    for name, expected_slot in current_slot_registers.items():
        assert _logical_slot_from_key(name) == expected_slot
