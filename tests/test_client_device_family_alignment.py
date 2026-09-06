import pytest

from grobro.grobro.client import _known_registers_for_device
from grobro.model.device_family import get_known_registers


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
def test_client_register_selection_matches_central_device_family_registry(device_id):
    assert _known_registers_for_device(device_id) is get_known_registers(device_id)
