from grobro.ha.firmware_client import compose_noah_firmware


def test_compose_noah_firmware_like_shinephone():
    payload = {
        "fw_version_part_1": 19,
        "fw_version_part_2": 19,
        "fw_version_part_3": 14,
    }

    assert compose_noah_firmware(payload, "4.0.1.9") == "19.19.14.4019"


def test_compose_noah_firmware_uses_dynamic_datalogger_version():
    payload = {
        "fw_version_part_1": 19,
        "fw_version_part_2": 19,
        "fw_version_part_3": 14,
    }

    assert compose_noah_firmware(payload, "4.0.2.0") == "19.19.14.4020"


def test_compose_noah_firmware_falls_back_to_device_version():
    payload = {
        "fw_version_part_1": 19,
        "fw_version_part_2": 19,
        "fw_version_part_3": 14,
    }

    assert compose_noah_firmware(payload, None) == "19.19.14"


def test_compose_noah_firmware_requires_all_device_parts():
    payload = {
        "fw_version_part_1": 19,
        "fw_version_part_2": 19,
        "fw_version_part_3": None,
    }

    assert compose_noah_firmware(payload, "4.0.1.9") is None
