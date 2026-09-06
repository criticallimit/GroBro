import base64
import json

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


def test_raw_dump_appends_all_messages_to_one_jsonl_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup.grobro_client_module, "DUMP_DIR", str(tmp_path))

    payload1 = b"\x00\x01\x02NOAH"
    payload2 = b"\xff\x10\x20GROWATT"

    cleanup._dump_message_binary_safe("c/33/DEVICE", payload1)
    cleanup._dump_message_binary_safe("s/DEVICE", payload2)

    dump_file = tmp_path / "messages.jsonl"
    assert dump_file.exists()

    records = [json.loads(line) for line in dump_file.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert records[0]["topic"] == "c/33/DEVICE"
    assert records[1]["topic"] == "s/DEVICE"
    assert records[0]["payload_length"] == len(payload1)
    assert records[1]["payload_length"] == len(payload2)
    assert base64.b64decode(records[0]["payload_base64"]) == payload1
    assert base64.b64decode(records[1]["payload_base64"]) == payload2


def test_cleanup_no_longer_duplicates_core_config_packet_builders():
    assert not hasattr(cleanup, "_build_config_read_message")
    assert not hasattr(cleanup, "_build_config_write_message")
    assert not hasattr(cleanup, "_validate_device_id")
    assert not hasattr(cleanup, "_validate_register_no")
