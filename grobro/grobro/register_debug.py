"""Passive register dump support for GroBro.

This module monkey-patches GrowattModbusMessage.parse_grobro so every successfully
parsed Modbus register block can be written to a JSONL file for reverse engineering.
It never sends Modbus requests or writes to a device.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import threading
from datetime import datetime, timezone

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


def _signed_16(value: int) -> int:
    return struct.unpack(">h", struct.pack(">H", value))[0]


def _write_message(message: GrowattModbusMessage) -> None:
    os.makedirs(REGISTER_DEBUG_DIR, exist_ok=True)
    path = os.path.join(REGISTER_DEBUG_DIR, "registers.jsonl")

    message_timestamp = None
    if message.metadata and message.metadata.timestamp:
        message_timestamp = message.metadata.timestamp.isoformat()

    now = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []

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

            record = {
                "captured_at": now,
                "device_timestamp": message_timestamp,
                "device_id": message.device_id,
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
            lines.append(json.dumps(record, separators=(",", ":")))

    if not lines:
        return

    with _LOCK:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
            handle.write("\n")


def install_register_debug_hook() -> None:
    """Install the passive parser hook once when REGISTER_DEBUG is enabled."""
    global _INSTALLED, _ORIGINAL_PARSE

    if _INSTALLED or not REGISTER_DEBUG:
        return

    _ORIGINAL_PARSE = GrowattModbusMessage.parse_grobro

    def parse_and_dump(buffer):
        message = _ORIGINAL_PARSE(buffer)
        if message is not None:
            try:
                _write_message(message)
            except Exception as exc:  # Debug logging must never break normal GroBro parsing.
                LOG.warning("Register debug dump failed: %s", exc)
        return message

    GrowattModbusMessage.parse_grobro = staticmethod(parse_and_dump)
    _INSTALLED = True
    LOG.warning(
        "Passive register debug enabled: dir=%s max_register=%s changes_only=%s",
        REGISTER_DEBUG_DIR,
        REGISTER_DEBUG_MAX_REGISTER,
        REGISTER_DEBUG_CHANGES_ONLY,
    )
