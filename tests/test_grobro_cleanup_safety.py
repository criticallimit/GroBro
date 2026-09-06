from unittest.mock import patch

from grobro.grobro import cleanup
from grobro.grobro.builder import scramble
from grobro.grobro.cleanup import _noah_heater_state_from_packet


def _noah_status_packet(heater_value: int, message_type: int = 0x0104) -> bytes:
    plain = bytearray(109)
    plain[6:8] = message_type.to_bytes(2, "big")
    plain[108] = heater_value
    return scramble(bytes(plain))


def test_noah_heater_uses_validated_status_frame_byte():
    assert _noah_heater_state_from_packet(_noah_status_packet(0), "0PVPTEST") == "Off"
    assert _noah_heater_state_from_packet(_noah_status_packet(1), "0PVPTEST") == "1 On"
    assert _noah_heater_state_from_packet(_noah_status_packet(7), "0PVPTEST") == "1&2&3 On"
    assert _noah_heater_state_from_packet(_noah_status_packet(15), "0PVPTEST") == "All On"


def test_noah_heater_does_not_guess_unsupported_packets():
    assert _noah_heater_state_from_packet(_noah_status_packet(1), "QMNTEST") is None
    assert _noah_heater_state_from_packet(_noah_status_packet(1), "0HVRTEST") is None
    assert _noah_heater_state_from_packet(_noah_status_packet(1, 0x0103), "0PVPTEST") is None
    assert _noah_heater_state_from_packet(_noah_status_packet(16), "0PVPTEST") is None
    assert _noah_heater_state_from_packet(b"short", "0PVPTEST") is None


def test_raw_dump_wrapper_delegates_to_centralized_dumper(monkeypatch):
    monkeypatch.setattr(cleanup.grobro_client_module, "DUMP_DIR", "/tmp/grobro-dump")

    with patch("grobro.grobro.cleanup.dump_message_jsonl") as dump:
        cleanup._dump_message_binary_safe("c/33/DEVICE", b"payload")

    dump.assert_called_once_with("/tmp/grobro-dump", "c/33/DEVICE", b"payload")


def test_cleanup_no_longer_duplicates_core_config_packet_builders():
    assert not hasattr(cleanup, "_build_config_read_message")
    assert not hasattr(cleanup, "_build_config_write_message")
    assert not hasattr(cleanup, "_validate_device_id")
    assert not hasattr(cleanup, "_validate_register_no")
