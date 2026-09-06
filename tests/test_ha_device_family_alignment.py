import pytest

from grobro.ha.client import get_device_type_name as ha_get_device_type_name
from grobro.ha.client import get_known_registers as ha_get_known_registers
from grobro.model.device_family import get_device_type_name, get_known_registers


@pytest.mark.parametrize(
    "device_id",
    [
        "0PVP50ZR175T00E8",
        "0HVR000000000001",
        "QMN000BZP4N991ML",
        "PTQ000000000001",
        "RAQ000000000001",
        "HAQ000000000001",
        "ZGQ000000000001",
        "VWQ000000000001",
        "UNKNOWN000000001",
    ],
)
def test_ha_register_selection_matches_central_device_family_registry(device_id):
    assert ha_get_known_registers(device_id) is get_known_registers(device_id)


@pytest.mark.parametrize(
    "device_id",
    [
        "0PVP50ZR175T00E8",
        "0HVR000000000001",
        "QMN000BZP4N991ML",
        "PTQ000000000001",
        "RAQ000000000001",
        "HAQ000000000001",
        "ZGQ000000000001",
        "VWQ000000000001",
        "UNKNOWN000000001",
    ],
)
def test_ha_device_name_matches_central_device_family_registry(device_id):
    assert ha_get_device_type_name(device_id) == get_device_type_name(device_id)
