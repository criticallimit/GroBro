import struct

import pytest

from grobro.grobro import register_debug
from grobro.model.modbus_message import GrowattModbusBlock, GrowattModbusMessage


@pytest.fixture
def capture(monkeypatch):
    records = []
    monkeypatch.setattr(register_debug, "REGISTER_DEBUG_CHANGES_ONLY", True)
    monkeypatch.setattr(register_debug, "_LAST_VALUES", {})
    monkeypatch.setattr(register_debug, "_LAST_BLOCK_VALUES", {})
    monkeypatch.setattr(register_debug, "_append_records", records.extend)
    return records


def message(start, values, device="TEST", function=4):
    return GrowattModbusMessage(
        unknown=0, device_id=device, function=function,
        register_blocks=[GrowattModbusBlock(
            start=start, end=start + len(values) - 1,
            values=struct.pack(">" + "H" * len(values), *values),
        )],
    )


@pytest.mark.parametrize("start, values, register, previous", [
    (95, [3, 4], 95, 3),
    (93, [7, 8], 94, 8),
    (93, [7, 8, 9, 10], 94, 8),
    (94, [8], 94, 8),
])
def test_overlapping_layout_preserves_returning_changes(capture, start, values, register, previous):
    first = message(94, [1, 2])
    register_debug._write_modbus_message(first)
    register_debug._write_modbus_message(message(start, values))
    capture.clear()
    register_debug._write_modbus_message(first)
    record = next(record for record in capture if record["register"] == register)
    assert record["previous"] == previous
    assert record["uint16"] == [1, 2][register - 94]
    assert register_debug._LAST_VALUES[("TEST", 4, register)] == record["uint16"]


@pytest.mark.parametrize("other", [
    message(96, [3, 4]),
    message(94, [3, 4], device="OTHER"),
    message(94, [3, 4], function=3),
])
def test_unrelated_blocks_preserve_fast_path(capture, monkeypatch, other):
    first = message(94, [1, 2])
    register_debug._write_modbus_message(first)
    register_debug._write_modbus_message(other)
    capture.clear()

    def unexpected_unpack(*args, **kwargs):
        pytest.fail("Unrelated block invalidated the unchanged-block fast path")

    monkeypatch.setattr(register_debug.struct, "unpack_from", unexpected_unpack)
    register_debug._write_modbus_message(first)
    assert capture == []


def test_overlapping_blocks_in_one_message_keep_frame_order(capture):
    first = message(94, [1, 2])
    first.register_blocks.append(message(95, [3, 4]).register_blocks[0])
    register_debug._write_modbus_message(first)
    capture.clear()
    register_debug._write_modbus_message(first)
    assert [(r["register"], r["previous"], r["uint16"]) for r in capture] == [
        (95, 3, 2), (95, 2, 3),
    ]


def test_overlap_with_equal_values_does_not_emit_false_change(capture):
    first = message(94, [1, 2])
    register_debug._write_modbus_message(first)
    register_debug._write_modbus_message(message(95, [2, 4]))
    capture.clear()
    register_debug._write_modbus_message(first)
    assert capture == []
