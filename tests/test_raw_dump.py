import base64
import json

from grobro.grobro.raw_dump import dump_message_jsonl


def test_raw_dump_appends_lossless_messages_to_one_jsonl_file(tmp_path):
    payload1 = b"\x00\x01\x02NOAH"
    payload2 = b"\xff\x10\x20GROWATT"

    dump_message_jsonl(str(tmp_path), "c/33/DEVICE", payload1)
    dump_message_jsonl(str(tmp_path), "s/DEVICE", payload2)

    dump_file = tmp_path / "messages.jsonl"
    records = [json.loads(line) for line in dump_file.read_text(encoding="utf-8").splitlines()]

    assert len(records) == 2
    assert records[0]["topic"] == "c/33/DEVICE"
    assert records[1]["topic"] == "s/DEVICE"
    assert records[0]["payload_length"] == len(payload1)
    assert records[1]["payload_length"] == len(payload2)
    assert base64.b64decode(records[0]["payload_base64"]) == payload1
    assert base64.b64decode(records[1]["payload_base64"]) == payload2


def test_raw_dump_rejects_non_bytes_without_creating_data(tmp_path, caplog):
    dump_message_jsonl(str(tmp_path), "c/33/DEVICE", "not-bytes")
    assert not (tmp_path / "messages.jsonl").exists()
    assert "payload must be bytes-like" in caplog.text
