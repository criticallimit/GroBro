from grobro.model.growatt_registers import KNOWN_NOAH_REGISTERS


def test_noah_bat2_bat3_cell_voltage_registers_are_published_like_bat1():
    expected = {
        "maxcvbat1": (99, "Battery 1 max. Cell Voltage"),
        "mincvbat1": (100, "Battery 1 min. Cell Voltage"),
        "maxcvbat2": (375, "Battery 2 max. Cell Voltage"),
        "mincvbat2": (376, "Battery 2 min. Cell Voltage"),
        "maxcvbat3": (382, "Battery 3 max. Cell Voltage"),
        "mincvbat3": (383, "Battery 3 min. Cell Voltage"),
        "maxcvbat4": (389, "Battery 4 max. Cell Voltage"),
        "mincvbat4": (390, "Battery 4 min. Cell Voltage"),
    }

    for name, (register_no, display_name) in expected.items():
        register = KNOWN_NOAH_REGISTERS.input_registers[name]

        assert register.growatt.position.register_no == register_no
        assert register.growatt.position.size == 2
        assert register.growatt.data.data_type == "FLOAT"
        assert register.growatt.data.float_options is not None
        assert register.growatt.data.float_options.multiplier == 0.001
        assert register.homeassistant.publish is True
        assert register.homeassistant.name == display_name
        assert register.homeassistant.state_class == "measurement"
        assert register.homeassistant.device_class == "voltage"
        assert register.homeassistant.unit_of_measurement == "V"
        assert register.homeassistant.icon == "mdi:flash"
        assert register.homeassistant.suggested_display_precision == 3
