"""Passive register dump support for GroBro.

This module hooks GroBro's existing parsers so received Modbus register blocks can
be written to JSONL for reverse engineering. It never sends additional Modbus
requests and never writes to a device.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import threading
from datetime import datetime, timezone

from grobro.grobro import parser as growatt_parser
from grobro.grobro.noah_0103 import find_embedded_register_block
from grobro.model.modbus_message import GrowattModbusMessage

LOG = logging.getLogger(__name__)

REGISTER_DEBUG = os.getenv("REGISTER_DEBUG", "false").lower() == "true"
REGISTER_DEBUG_DIR = os.getenv("REGISTER_DEBUG_DIR", "/share/GroBro/register_debug")
REGISTER_DEBUG_CHANGES_ONLY = (
    os.getenv("REGISTER_DEBUG_CHANGES_ONLY", "true").lower() == "true"
)

try:
    REGISTER_DEBUG_MAX_REGISTER = int(
        os.getenv("REGISTER_DEBUG_MAX_REGISTER", "65535")
    )
except (TypeError, ValueError):
    REGISTER_DEBUG_MAX_REGISTER = 65535
    LOG.warning("Invalid REGISTER_DEBUG_MAX_REGISTER; falling back to 65535")

REGISTER_DEBUG_MAX_REGISTER = max(0, min(65535, REGISTER_DEBUG_MAX_REGISTER))

# Passive watch-only registers discovered in the embedded NOAH 0x0103 holding
# block. Their semantics are intentionally unknown. They must not become HA
# entities or writable controls until independently validated.
NOAH_0103_WATCH_REGISTERS = frozenset(range(299, 305))
NOAH_0103_WATCH_GROUP = "noah_r299_r304_unknown_descriptor"

_LOCK = threading.Lock()
_LAST_VALUES: dict[tuple[str, int, int], int] = {}
_INSTALLED = False
_ORIGINAL_PARSE = None
_ORIGINAL_NOAH_0103 = None


def _signed_16(value: int) -> int:
    return struct.unpack(">h", struct.pack(">H", value))[0]


def _append_records(records: list[dict]) -> None:
    if not records:
        return
    os.makedirs(REGISTER_DEBUG_DIR, exist_ok=True)
    path = os.path.join(REGISTER_DEBUG_DIR, "registers.jsonl")
    with _LOCK:
        with open(path, "a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, separators=(",", ":")))
                handle.write("\n")


def _write_modbus_message(message: GrowattModbusMessage) -> None:
    message_timestamp = None
    if message.metadata and message.metadata.timestamp:
        message_timestamp = message.metadata.timestamp.isoformat()

    now = datetime.now(timezone.utc).isoformat()
    records: list[dict] = []

    for block in message.register_blocks:
        if block is None:
            continue
        for register_no in range(block.start, block.end + 1):
            if register_no < 0 or register_no > REGISTER_DEBUG_MAX_REGISTER:
                continue

            offset = (register_no - block.start) * 2
            if offset + 2 > len(block.values):
                continue

            value = struct.unpack_from(">H", block.values, offset)[0]
            key = (message.device_id, int(message.function), register_no)
            previous = _LAST_VALUES.get(key)
            changed = previous is None or previous != value
            _LAST_VALUES[key] = value

            if REGISTER_DEBUG_CHANGES_ONLY and not changed:
                continue

            records.append(
                {
                    "captured_at": now,
                    "device_timestamp": message_timestamp,
                    "device_id": message.device_id,
                    "source": "modbus",
                    "function": int(message.function),
                    "block_start": block.start,
                    "block_end": block.end,
                    "register": register_no,
                    "uint16": value,
                    "int16": _signed_16(value),
                    "hex": f"0x{value:04X}",
                    "high_byte": (value >> 8) & 0xFF,
                    "low_byte": value & 0xFF,
                    "previous": previous,
                    "changed": changed,
                }
            )

    _append_records(records)


def _write_noah_0103(result: dict) -> None:
    """Record both opaque 0x0103 values and any confirmed embedded Modbus block."""
    now = datetime.now(timezone.utc).isoformat()
    device_id = result.get("device_id", "")
    records: list[dict] = []

    # Preserve the historical/raw view by value index because the prefix portion
    # of 0x0103 remains only partially understood.
    for value_index, value in enumerate(result.get("registers", [])):
        key = (device_id, 0x0103, value_index)
        previous = _LAST_VALUES.get(key)
        changed = previous is None or previous != value
        _LAST_VALUES[key] = value
        if REGISTER_DEBUG_CHANGES_ONLY and not changed:
            continue

        records.append(
            {
                "captured_at": now,
                "device_timestamp": None,
                "device_id": device_id,
                "source": "noah_0103",
                "message_type": "0x0103",
                "addressing": "unknown",
                "value_index": value_index,
                "value_count": result.get(
                    "register_count",
                    len(result.get("registers", [])),
                ),
                "uint16": value,
                "int16": _signed_16(value),
                "hex": f"0x{value:04X}",
                "high_byte": (value >> 8) & 0xFF,
                "low_byte": value & 0xFF,
                "previous": previous,
                "changed": changed,
            }
        )

    embedded = result.get("embedded_register_block")
    if isinstance(embedded, dict):
        start = embedded.get("start")
        end = embedded.get("end")
        values = embedded.get("values", [])
        block_offset = embedded.get("offset")
        if isinstance(start, int) and isinstance(end, int):
            for index, value in enumerate(values):
                register_no = start + index
                if register_no > end or register_no > REGISTER_DEBUG_MAX_REGISTER:
                    break
                # Separate cache namespace from raw-index records and ordinary
                # Modbus callbacks while still exposing function=3 in the JSON.
                key = (device_id, 0x010303, register_no)
                previous = _LAST_VALUES.get(key)
                changed = previous is None or previous != value
                _LAST_VALUES[key] = value
                if REGISTER_DEBUG_CHANGES_ONLY and not changed:
                    continue

                record = {
                    "captured_at": now,
                    "device_timestamp": None,
                    "device_id": device_id,
                    "source": "noah_0103_modbus",
                    "message_type": "0x0103",
                    "function": 3,
                    "block_offset": block_offset,
                    "block_start": start,
                    "block_end": end,
                    "register": register_no,
                    "uint16": value,
                    "int16": _signed_16(value),
                    "hex": f"0x{value:04X}",
                    "high_byte": (value >> 8) & 0xFF,
                    "low_byte": value & 0xFF,
                    "previous": previous,
                    "changed": changed,
                }

                if register_no in NOAH_0103_WATCH_REGISTERS:
                    record.update(
                        {
                            "watch_register": True,
                            "watch_group": NOAH_0103_WATCH_GROUP,
                            "watch_reason": (
                                "Unknown NOAH 0x0103 descriptor candidate; "
                                "observed R299=800, R300=257, R301-R304=0xFFFF"
                            ),
                        }
                    )
                    if previous is not None and changed:
                        LOG.warning(
                            "NOAH 0x0103 watch register changed: device=%s "
                            "register=%s previous=%s current=%s",
                            device_id,
                            register_no,
                            previous,
                            value,
                        )

                records.append(record)

    _append_records(records)


def install_register_debug_hook() -> None:
    """Install passive parser hooks once when REGISTER_DEBUG is enabled."""
    global _INSTALLED, _ORIGINAL_PARSE, _ORIGINAL_NOAH_0103

    if _INSTALLED or not REGISTER_DEBUG:
        return

    _ORIGINAL_PARSE = GrowattModbusMessage.parse_grobro

    def parse_and_dump(buffer):
        message = _ORIGINAL_PARSE(buffer)
        if message is not None:
            try:
                _write_modbus_message(message)
            except Exception as exc:
                LOG.warning("Register debug dump failed: %s", exc)
        return message

    GrowattModbusMessage.parse_grobro = staticmethod(parse_and_dump)

    _ORIGINAL_NOAH_0103 = growatt_parser.NOAH_DECODERS.get(0x0103)
    if _ORIGINAL_NOAH_0103 is not None:

        def parse_noah_0103_and_dump(data):
            result = _ORIGINAL_NOAH_0103(data)
            try:
                block = find_embedded_register_block(data)
                if block is not None:
                    result["embedded_register_block"] = {
                        "offset": block.offset,
                        "start": block.start,
                        "end": block.end,
                        "values": list(block.values),
                    }
                _write_noah_0103(result)
            except Exception as exc:
                LOG.warning("NOAH 0x0103 debug dump failed: %s", exc)
            return result

        growatt_parser.NOAH_DECODERS[0x0103] = parse_noah_0103_and_dump

    _INSTALLED = True
    LOG.warning(
        "Passive register debug enabled: dir=%s max_register=%s changes_only=%s",
        REGISTER_DEBUG_DIR,
        REGISTER_DEBUG_MAX_REGISTER,
        REGISTER_DEBUG_CHANGES_ONLY,
    )
