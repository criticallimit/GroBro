"""Regression cases for NEXA temperatures recorded in upstream GroBro issue #240.

https://github.com/robertzaage/GroBro/issues/240
Battery-pack 3/4 temperature register assignments remain unverified.
"""
import struct

import pytest

from grobro.model.growatt_registers import KNOWN_NEXA_REGISTERS


@pytest.mark.parametrize(("name", "register", "raw", "expected"), [
    ("battery1Temp", 30, 2821, 9.0),
    ("battery2Temp", 42, 2781, 5.0),
    ("pv1Temp", 94, 2827, 9.6),
    ("pv2Temp", 97, 2827, 9.6),
    ("systemTemp", 98, 2835, 10.4),
    ("pv3Temp", 105, 2845, 11.4),
    ("pv4Temp", 108, 2845, 11.4),
])
def test_nexa_observed_tenth_kelvin_temperatures(name, register, raw, expected):
    entry = KNOWN_NEXA_REGISTERS.input_registers[name]
    assert entry.growatt.position.register_no == register
    assert entry.growatt.data.parse(struct.pack("!H", raw)) == pytest.approx(expected)
    assert entry.homeassistant.device_class == "temperature"
    assert entry.homeassistant.publish is True


def test_unverified_nexa_battery_temperature_registers_not_exposed():
    assert "battery3Temp" not in KNOWN_NEXA_REGISTERS.input_registers
    assert "battery4Temp" not in KNOWN_NEXA_REGISTERS.input_registers
