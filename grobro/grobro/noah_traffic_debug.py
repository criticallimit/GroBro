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


_INSTALLED = False


def _device_id_from_topic(topic: str) -> str:
    from grobro.grobro import client as client_module

    try:
        return client_module._extract_device_id(str(topic))
    except Exception:
        return ""


def _safe_unscramble(payload):
    from grobro.grobro import parser

    try:
        return parser.unscramble(payload)
    except Exception:
        return None


def install_noah_traffic_debug_hook() -> None:
    """Capture all NOAH traffic already flowing through GroBro when enabled."""
    global _INSTALLED
    if _INSTALLED or not REGISTER_DEBUG:
        return

    from grobro.grobro import client as client_module

    original_device_message = client_module.Client._Client__on_message
    original_cloud_message = client_module.Client._Client__on_message_forward_client
    original_publish_checked = client_module._publish_checked

    def device_message(self, client, userdata, msg):
        device_id = _device_id_from_topic(msg.topic)
        if device_id.startswith("0PVP"):
            capture_noah_mqtt_traffic(
                device_id=device_id,
                direction="device_to_grobro",
                topic=msg.topic,
                payload=msg.payload,
                decoded=_safe_unscramble(msg.payload),
                qos=getattr(msg, "qos", None),
                retain=getattr(msg, "retain", None),
                forwarded_for=client_module.get_property(msg, "forwarded-for"),
            )
        return original_device_message(self, client, userdata, msg)

    def cloud_message(self, client, userdata, msg):
        device_id = _device_id_from_topic(msg.topic)
        if device_id.startswith("0PVP"):
            capture_noah_mqtt_traffic(
                device_id=device_id,
                direction="cloud_to_grobro",
                topic=msg.topic,
                payload=msg.payload,
                decoded=_safe_unscramble(msg.payload),
                qos=getattr(msg, "qos", None),
                retain=getattr(msg, "retain", None),
                forwarded_for=client_module.get_property(msg, "forwarded-for"),
            )
        return original_cloud_message(self, client, userdata, msg)

    def publish_checked(client, topic: str, payload=None, **kwargs):
        device_id = _device_id_from_topic(topic)
        if device_id.startswith("0PVP") and payload is not None and "/33/" in str(topic):
            properties = kwargs.get("properties")
            if properties is client_module.MQTT_PROP_FORWARD_GROWATT:
                direction = "grobro_to_device_from_cloud"
            elif properties is client_module.MQTT_PROP_FORWARD_HA:
                direction = "grobro_to_device_from_ha"
            else:
                direction = "grobro_to_cloud_or_device"
            capture_noah_mqtt_traffic(
                device_id=device_id,
                direction=direction,
                topic=topic,
                payload=payload,
                decoded=_safe_unscramble(payload),
                qos=kwargs.get("qos"),
                retain=kwargs.get("retain"),
                forwarded_for=None,
            )
        return original_publish_checked(client, topic, payload, **kwargs)

    client_module.Client._Client__on_message = device_message
    client_module.Client._Client__on_message_forward_client = cloud_message
    client_module._publish_checked = publish_checked
    _INSTALLED = True
    LOG.warning("Passive full NOAH MQTT traffic capture hook installed")
