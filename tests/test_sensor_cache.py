"""Contract tests for NOAH upstream sensors and Better GroBro cache semantics."""
from types import SimpleNamespace

from grobro.ha.sensor_cache import MAX_AGE_SECONDS, merge_state, saved_max_bat, flush
from grobro.ha.client import get_known_registers


def test_noah_temperature_and_soh_registers():
    regs = get_known_registers("0PVP000000000001").input_registers
    for key, number in (("pv1_temp", 94), ("pv2_temp", 97), ("system_temp", 98), ("bat_soh", 102)):
        assert regs[key].growatt.position.register_no == number
        assert regs[key].homeassistant.publish


def test_cache_preserves_battery_values_but_not_live_power(tmp_path, monkeypatch):
    monkeypatch.setenv("BETTER_GROBRO_STATE_DIR", str(tmp_path))
    client = SimpleNamespace()
    registers = get_known_registers("0PVP000000000001")
    initial = {"bat2_temp": 24.1, "bat_2_soc_pct": 75, "out_power": 310}
    merge_state(client, "0PVP000000000001", initial, registers, detected_bat_count=2, max_bat=2)
    assert saved_max_bat(client, "0PVP000000000001") == 2
    disconnected = merge_state(client, "0PVP000000000001", {"bat2_temp": 0, "out_power": 0}, registers, detected_bat_count=1, max_bat=2)
    assert disconnected["bat2_temp"] == 24.1
    assert disconnected["bat_2_soc_pct"] == 75
    assert disconnected["out_power"] == 0
    flush(client, force=True)
    fresh = SimpleNamespace()
    assert saved_max_bat(fresh, "0PVP000000000001") == 2
    restored = merge_state(fresh, "0PVP000000000001", {}, registers, detected_bat_count=1, max_bat=2)
    assert restored["bat2_temp"] == 24.1


def test_stale_values_are_not_restored(tmp_path, monkeypatch):
    import json
    import time
    monkeypatch.setenv("BETTER_GROBRO_STATE_DIR", str(tmp_path))
    device = "0PVP000000000001"
    (tmp_path / ("state_" + device + ".json")).write_text(json.dumps({
        "max_bat": 2,
        "values": {"bat2_temp": {"value": 19.5, "observed_at": time.time() - MAX_AGE_SECONDS - 60}},
    }), encoding="utf-8")
    result = merge_state(SimpleNamespace(), device, {}, get_known_registers(device), detected_bat_count=1, max_bat=2)
    assert "bat2_temp" not in result
