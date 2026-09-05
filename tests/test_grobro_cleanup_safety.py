import base64
import json
from types import SimpleNamespace

from grobro.grobro import cleanup
from grobro.grobro.cleanup import _get_property_safe, _safe_topic_segment


def test_safe_topic_segment_blocks_path_traversal():
    assert _safe_topic_segment("..") == "_"
    assert _safe_topic_segment("../secret") == "_secret"
    assert _safe_topic_segment("0PVP50ZR175T00E8") == "0PVP50ZR175T00E8"


def test_get_property_safe_handles_missing_properties():
    assert _get_property_safe(SimpleNamespace(properties=None), "forwarded-for") is None


def test_get_property_safe_reads_user_property():
    props = SimpleNamespace(
        json=lambda: {"UserProperty": [("forwarded-for", "growatt")]}
    )
    msg = SimpleNamespace(properties=props)
    assert _get_property_safe(msg, "forwarded-for") == "growatt"


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
