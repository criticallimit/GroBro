from grobro.model.device_family import (
    get_device_family,
    get_device_type_name,
    get_known_registers,
    supports_time_sync,
    uses_dynamic_pv_count,
)
from grobro.model.growatt_registers import (
    KNOWN_MOD_REGISTERS,
    KNOWN_NEO_REGISTERS,
    KNOWN_NEXA_REGISTERS,
    KNOWN_NOAH_REGISTERS,
    KNOWN_SPF_REGISTERS,
    KNOWN_XH2_REGISTERS,
)


def test_all_known_device_prefixes_resolve_consistently():
    cases = {
        "0PVPTEST": ("NOAH", KNOWN_NOAH_REGISTERS),
        "0HVRTEST": ("NEXA", KNOWN_NEXA_REGISTERS),
        "QMNTEST": ("NEO", KNOWN_NEO_REGISTERS),
        "PTQTEST": ("NEO", KNOWN_NEO_REGISTERS),
        "RAQTEST": ("ShineWeLink", KNOWN_NEO_REGISTERS),
        "HAQTEST": ("SPF", KNOWN_SPF_REGISTERS),
        "ZGQTEST": ("MIN-XH2", KNOWN_XH2_REGISTERS),
        "VWQTEST": ("MOD", KNOWN_MOD_REGISTERS),
    }

    for device_id, (name, registers) in cases.items():
        assert get_device_family(device_id) is not None
        assert get_device_type_name(device_id) == name
        assert get_known_registers(device_id) is registers


def test_unknown_device_is_not_guessed():
    assert get_device_family("UNKNOWN") is None
    assert get_device_type_name("UNKNOWN") == "UNKNOWN"
    assert get_known_registers("UNKNOWN") is None


def test_clock_sync_capability_is_explicit():
    # Every current inverter/device register map that explicitly exposes
    # system_time as config register 31 uses the shared automatic sync path.
    for device_id in (
        "0PVPTEST",  # NOAH
        "0HVRTEST",  # NEXA
        "QMNTEST",   # NEO
        "PTQTEST",   # NEO behind ShineWeLink
        "HAQTEST",   # SPF
        "ZGQTEST",   # MIN-XH2
        "VWQTEST",   # MOD
    ):
        assert supports_time_sync(device_id) is True

    # RAQ is the ShineWeLink gateway itself; time writes belong to the PTQ
    # inverter discovered behind it, never the gateway serial.
    assert supports_time_sync("RAQTEST") is False


def test_dynamic_pv_detection_capability_is_explicit():
    assert uses_dynamic_pv_count("QMNTEST") is True
    assert uses_dynamic_pv_count("PTQTEST") is True
    assert uses_dynamic_pv_count("VWQTEST") is True
    assert uses_dynamic_pv_count("0PVPTEST") is False
    assert uses_dynamic_pv_count("0HVRTEST") is False
