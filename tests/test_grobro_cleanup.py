from grobro.grobro.builder import scramble
from grobro.grobro.cleanup import _is_blocked_cloud_config_message


def _packet(message_type: int) -> bytes:
    decoded = (
        b"\x00\x01\x00\x07\x00\x20"
        + message_type.to_bytes(2, "big")
        + b"0PVPTEST".ljust(32, b"\x00")
    )
    return scramble(decoded)


def test_cloud_config_filter_detects_config_write():
    assert _is_blocked_cloud_config_message(_packet(0x0118)) is True


def test_cloud_config_filter_detects_noah_preset_multiple_family():
    assert _is_blocked_cloud_config_message(_packet(0x0110)) is True


def test_cloud_config_filter_allows_telemetry():
    assert _is_blocked_cloud_config_message(_packet(0x0104)) is False


def test_cloud_config_filter_handles_short_payload():
    assert _is_blocked_cloud_config_message(b"\x00\x01") is False
