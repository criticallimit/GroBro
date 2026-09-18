from grobro.ha.firmware_runtime import (
    _firmware_part_names_for_device,
    _supports_combined_firmware,
    compose_combined_firmware,
)


def test_shared_protocol_capability_covers_noah_and_nexa_only():
    assert _supports_combined_firmware("0PVPTEST00000001") is True
    assert _supports_combined_firmware("0HVRTEST00000001") is True
    assert _supports_combined_firmware("QMNTEST000000001") is False


def test_firmware_part_layout_is_cached_per_device():
    _firmware_part_names_for_device.cache_clear()

    first = _firmware_part_names_for_device("0PVPTEST00000001")
    info_after_first = _firmware_part_names_for_device.cache_info()
    second = _firmware_part_names_for_device("0PVPTEST00000001")
    info_after_second = _firmware_part_names_for_device.cache_info()

    assert first
    assert second == first
    assert info_after_first.misses == 1
    assert info_after_second.hits == 1


def test_cached_noah_firmware_parts_compose_shinephone_version():
    names = _firmware_part_names_for_device("0PVPTEST00000001")
    payload = {
        name: value
        for name, value in zip(names, ("19", "19", "14"), strict=False)
    }

    assert compose_combined_firmware(
        payload,
        "4.0.1.9",
        names,
    ) == "19.19.14.4019"


def test_cached_nexa_firmware_parts_compose_shinephone_version():
    names = _firmware_part_names_for_device("0HVRTEST00000001")
    payload = {
        name: value
        for name, value in zip(names, ("14", "12", "14", "11"), strict=False)
    }

    assert compose_combined_firmware(
        payload,
        "4.0.1.9",
        names,
    ) == "14.12.14.11.4019"
