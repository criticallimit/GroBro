from grobro.model.device_family import (
    DEVICE_FAMILIES,
    get_device_family,
    get_device_type_name,
    get_known_registers,
    is_gateway,
    is_known_device,
    supports_time_sync,
    uses_dynamic_pv_count,
)
from grobro.model.growatt_registers import (
    GrowattRegisterDataTypes,
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
        assert is_known_device(device_id) is True
        assert get_device_type_name(device_id) == name
        assert get_known_registers(device_id) is registers


def test_unknown_device_is_not_guessed():
    assert get_device_family("UNKNOWN") is None
    assert is_known_device("UNKNOWN") is False
    assert is_gateway("UNKNOWN") is False
    assert get_device_type_name("UNKNOWN") == "UNKNOWN"
    assert get_known_registers("UNKNOWN") is None


def test_gateway_capability_is_explicit():
    assert is_gateway("RAQTEST") is True
    for device_id in (
        "0PVPTEST",
        "0HVRTEST",
        "QMNTEST",
        "PTQTEST",
        "HAQTEST",
        "ZGQTEST",
        "VWQTEST",
    ):
        assert is_gateway(device_id) is False


def test_clock_sync_capability_is_derived_from_register_map():
    for device_id in (
        "0PVPTEST",
        "0HVRTEST",
        "QMNTEST",
        "PTQTEST",
        "HAQTEST",
        "ZGQTEST",
        "VWQTEST",
    ):
        assert supports_time_sync(device_id) is True

    assert supports_time_sync("RAQTEST") is False


def test_every_time_sync_family_has_system_time_register_31():
    for family in DEVICE_FAMILIES:
        supported_device = family.prefixes[0] + "TEST"
        if not supports_time_sync(supported_device):
            continue
        system_time = family.registers.config_registers.get("system_time")
        assert system_time is not None, family.key
        assert system_time.growatt.register_no == 31, family.key
        assert system_time.growatt.data.data_type == GrowattRegisterDataTypes.STRING, family.key


def test_dynamic_pv_detection_capability_is_explicit():
    assert uses_dynamic_pv_count("QMNTEST") is True
    assert uses_dynamic_pv_count("PTQTEST") is True
    assert uses_dynamic_pv_count("VWQTEST") is True
    assert uses_dynamic_pv_count("0PVPTEST") is False
    assert uses_dynamic_pv_count("0HVRTEST") is False
