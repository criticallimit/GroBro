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
from grobro.model.modbus_message import GrowattModbusMessage

LOG = logging.getLogger(__name__)

REGISTER_DEBUG = os.getenv("REGISTER_DEBUG", "false").lower() == "true"
REGISTER_DEBUG_DIR = os.getenv("REGISTER_DEBUG_DIR", "/share/GroBro/register_debug")
REGISTER_DEBUG_MAX_REGISTER = int(os.getenv("REGISTER_DEBUG_MAX_REGISTER", "3000"))
REGISTER_DEBUG_CHANGES_ONLY = (
    os.getenv("REGISTER_DEBUG_CHANGES_ONLY", "false").lower() == "true"
)

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
    """Record NOAH 0x0103 holding-register dumps.

    GroBro's current decoder exposes the values as a sequential list without an
    explicit start address. We retain them as registers 0..N-1 and mark that
    addressing assumption explicitly in every record.
    """
    now = datetime.now(timezone.utc).isoformat()
    device_id = result.get("device_id", "")
    records: list[dict] = []

    for register_no, value in enumerate(result.get("registers", [])):
        if register_no > REGISTER_DEBUG_MAX_REGISTER:
            break
        key = (device_id, 3, register_no)
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
                "function": 3,
                "message_type": "0x0103",
                "address_assumption": "sequential_from_zero",
                "block_start": 0,
                "block_end": max(0, result.get("register_count", 0) - 1),
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
