import base64
import json

import pytest

from grobro.grobro import cleanup
from grobro.grobro.cleanup import (
    _build_config_read_message,
    _build_config_write_message,
    _validate_device_id,
    _validate_register_no,
)


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


def test_config_message_validation_rejects_bad_wire_values():
    assert len(_validate_device_id("0PVP50ZR175T00E8")) == 16
    assert _validate_register_no(65535) == 65535

    with pytest.raises(ValueError):
        _validate_device_id("")
    with pytest.raises(ValueError):
        _validate_device_id("TOO-LONG-DEVICE-ID")
    with pytest.raises(ValueError):
        _validate_register_no(-1)
    with pytest.raises(ValueError):
        _validate_register_no(65536)


def test_config_builders_return_valid_wire_payloads():
    read_payload = _build_config_read_message("0PVP50ZR175T00E8", 17)
    write_payload = _build_config_write_message("0PVP50ZR175T00E8", 17, "secret")

    assert isinstance(read_payload, bytes)
    assert isinstance(write_payload, bytes)
    assert len(read_payload) > 40
    assert len(write_payload) > len(read_payload)
