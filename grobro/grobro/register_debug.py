"""Passive register dump support for GroBro.

The protocol client calls this module directly after parsing received Modbus and
NOAH 0x0103 data. Captures are written to JSONL for reverse engineering only;
this module never sends additional requests or writes to a device.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import threading
from datetime import datetime, timezone

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
# Fast path for change-only mode: most telemetry frames reuse the same register
# block layout, and many blocks are byte-for-byte identical to the previous one.
# Comparing the whole bytes object in C is much cheaper than walking every
# register in Python just to discover that none changed.
_LAST_BLOCK_VALUES: dict[tuple[str, int, int, int], bytes] = {}


def _signed_16(value: int) -> int:
    return struct.unpack(">h", struct.pack(">H", value))[0]


def _canonical_0103_device_id(raw_device_id: str) -> str:
    """Expand the shortened NEO identifier embedded in observed 0x0103 frames.

    Current NEO 0x0103 traffic carries only the ten-character serial suffix
    (for example BZP4N991ML), while the normal GroBro device identity is the
    full QMN000-prefixed serial. Keep this normalization diagnostic-only.
    """
    raw_device_id = str(raw_device_id or "").strip()
    if len(raw_device_id) == 10 and raw_device_id.isalnum():
        return f"QMN000{raw_device_id}"
    return raw_device_id


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
    function = int(message.function)

    for block in message.register_blocks:
        if block is None:
            continue

        if REGISTER_DEBUG_CHANGES_ONLY:
            block_key = (message.device_id, function, block.start, block.end)
            previous_block = _LAST_BLOCK_VALUES.get(block_key)
            if previous_block == block.values:
                continue
            _LAST_BLOCK_VALUES[block_key] = block.values

        for register_no in range(block.start, block.end + 1):
            if register_no < 0 or register_no > REGISTER_DEBUG_MAX_REGISTER:
                continue

            offset = (register_no - block.start) * 2
            if offset + 2 > len(block.values):
                continue

            value = struct.unpack_from(">H", block.values, offset)[0]
            key = (message.device_id, function, register_no)
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
                    "function": function,
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
    raw_device_id = result.get("device_id", "")
    device_id = _canonical_0103_device_id(raw_device_id)
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
                **(
                    {"raw_device_id": raw_device_id}
                    if raw_device_id != device_id
                    else {}
                ),
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
                    **(
                        {"raw_device_id": raw_device_id}
                        if raw_device_id != device_id
                        else {}
                    ),
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

def capture_modbus_message(message: GrowattModbusMessage | None) -> None:
    """Write one parsed Modbus message when passive register debug is enabled."""
    if not REGISTER_DEBUG or message is None:
        return
    try:
        _write_modbus_message(message)
    except Exception as exc:
        LOG.warning("Register debug dump failed: %s", exc)


def capture_noah_0103(data: bytes, result: dict | None) -> None:
    """Write one parsed NOAH 0x0103 message when passive debug is enabled."""
    if not REGISTER_DEBUG or not isinstance(result, dict):
        return
    try:
        debug_result = dict(result)
        block = find_embedded_register_block(data)
        if block is not None:
            debug_result["embedded_register_block"] = {
                "offset": block.offset,
                "start": block.start,
                "end": block.end,
                "values": list(block.values),
            }
        _write_noah_0103(debug_result)
    except Exception as exc:
        LOG.warning("NOAH 0x0103 debug dump failed: %s", exc)


def install_register_debug_hook() -> None:
    """Backward-compatible no-op; register diagnostics run directly in Client."""
    return None
