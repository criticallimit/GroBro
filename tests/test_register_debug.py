import json
import struct

from grobro.grobro import register_debug
from grobro.model.modbus_message import (
    GrowattModbusBlock,
    GrowattModbusFunction,
    GrowattModbusMessage,
)


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_changes_only_keeps_initial_state_and_then_only_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(register_debug, "REGISTER_DEBUG_DIR", str(tmp_path))
    monkeypatch.setattr(register_debug, "REGISTER_DEBUG_CHANGES_ONLY", True)
    monkeypatch.setattr(register_debug, "REGISTER_DEBUG_MAX_REGISTER", 3000)
    register_debug._LAST_VALUES.clear()

    block = GrowattModbusBlock(
        start=94,
        end=95,
        values=struct.pack(">HH", 3111, 100),
    )
    message = GrowattModbusMessage(
        unknown=0,
        device_id="0PVPTEST",
        function=GrowattModbusFunction.READ_INPUT_REGISTER,
        register_blocks=[block],
    )

    register_debug._write_modbus_message(message)
    register_debug._write_modbus_message(message)

    records = _read_jsonl(tmp_path / "registers.jsonl")
    assert [record["register"] for record in records] == [94, 95]
    assert records[0]["uint16"] == 3111
    assert records[1]["uint16"] == 100
    assert all(record["previous"] is None for record in records)

    message.register_blocks[0].values = struct.pack(">HH", 3112, 100)
    register_debug._write_modbus_message(message)

    records = _read_jsonl(tmp_path / "registers.jsonl")
    assert len(records) == 3
    assert records[-1]["register"] == 94
    assert records[-1]["previous"] == 3111
    assert records[-1]["uint16"] == 3112


def test_noah_0103_is_logged_as_index_not_confirmed_register(tmp_path, monkeypatch):
    monkeypatch.setattr(register_debug, "REGISTER_DEBUG_DIR", str(tmp_path))
    monkeypatch.setattr(register_debug, "REGISTER_DEBUG_CHANGES_ONLY", True)
    register_debug._LAST_VALUES.clear()

    register_debug._write_noah_0103(
        {
            "device_id": "0PVPTEST",
            "registers": [19, 19, 14, 100],
            "register_count": 4,
        }
    )

    records = _read_jsonl(tmp_path / "registers.jsonl")
    assert len(records) == 4
    assert [record["value_index"] for record in records] == [0, 1, 2, 3]
    assert all(record["addressing"] == "unknown" for record in records)
    assert all("register" not in record for record in records)
