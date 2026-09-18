from types import SimpleNamespace

from grobro.ha.battery_position import stabilize_battery_payload


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
