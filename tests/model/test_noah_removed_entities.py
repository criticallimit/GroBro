from grobro.model.growatt_registers import KNOWN_NOAH_REGISTERS


def test_removed_noah_entities_stay_out_of_runtime_map():
    assert "mqtt_ip" not in KNOWN_NOAH_REGISTERS.config_registers
    assert "pv1Temp" not in KNOWN_NOAH_REGISTERS.input_registers
    assert "pv2Temp" not in KNOWN_NOAH_REGISTERS.input_registers
    assert "systemTemp" not in KNOWN_NOAH_REGISTERS.input_registers


def test_noah_battery_soh_remains_available():
    assert "batterySoh" in KNOWN_NOAH_REGISTERS.input_registers
