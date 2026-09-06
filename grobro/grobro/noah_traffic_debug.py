"""Passive full MQTT traffic capture for NOAH devices.

The capture records traffic already passing through GroBro. It does not create
additional MQTT traffic, Modbus reads or device writes. The resulting JSONL may
contain sensitive configuration payloads and is intended only for diagnostics.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import struct
import threading
from datetime import datetime, timezone

from grobro.grobro.noah_protocol_debug import decode_interesting_noah_packet

LOG = logging.getLogger(__name__)

REGISTER_DEBUG = os.getenv("REGISTER_DEBUG", "false").lower() == "true"
REGISTER_DEBUG_DIR = os.getenv("REGISTER_DEBUG_DIR", "/share/GroBro/register_debug")

_LOCK = threading.Lock()


def _message_types(data: bytes | None) -> tuple[int | None, int | None]:
    if not data or len(data) < 8:
        return None, None
    try:
        return (
            struct.unpack_from(">H", data, 4)[0],
            struct.unpack_from(">H", data, 6)[0],
        )
    except struct.error:
        return None, None


def capture_noah_mqtt_traffic(
    *,
    device_id: str,
    direction: str,
    topic: str,
    payload: bytes,
    decoded: bytes | None = None,
    qos: int | None = None,
    retain: bool | None = None,
    forwarded_for: str | None = None,
) -> None:
    """Append one exact NOAH MQTT packet to the passive traffic log."""
    if not REGISTER_DEBUG or not str(device_id).startswith("0PVP"):
        return

    try:
        raw = bytes(payload)
        clear = bytes(decoded) if decoded is not None else None
        raw_type4, raw_type6 = _message_types(raw)
        clear_type4, clear_type6 = _message_types(clear)
        interpretation = decode_interesting_noah_packet(clear)
        record = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "device_id": device_id,
            "direction": direction,
            "topic": str(topic),
            "qos": qos,
            "retain": retain,
            "forwarded_for": forwarded_for,
            "payload_len": len(raw),
            "payload_b64": base64.b64encode(raw).decode("ascii"),
            "raw_msg_type_offset4": raw_type4,
            "raw_msg_type_offset6": raw_type6,
            "decoded_len": len(clear) if clear is not None else None,
            "decoded_b64": (
                base64.b64encode(clear).decode("ascii")
                if clear is not None
                else None
            ),
            "decoded_msg_type_offset4": clear_type4,
            "decoded_msg_type_offset6": clear_type6,
            "decoded_interpretation": interpretation,
        }
        os.makedirs(REGISTER_DEBUG_DIR, exist_ok=True)
        path = os.path.join(REGISTER_DEBUG_DIR, "noah_mqtt_traffic.jsonl")
        with _LOCK:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, separators=(",", ":")))
                handle.write("\n")
    except (OSError, TypeError, ValueError, struct.error) as exc:
        LOG.warning("NOAH MQTT traffic capture failed: %s", exc)
