"""Debug-fork-only Growatt runtime helpers.

Core protocol handling, cloud filtering, MQTT property parsing and shutdown logic
now live in the hardened core. This module intentionally contains only features
that are specific to this fork: the single-file raw dump, strict config-message
wire validation, and activation of the central device-family registry.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import struct
import threading
import time

from grobro.grobro import client as grobro_client_module
from grobro.grobro.builder import append_crc, scramble
from grobro.model.device_family import get_known_registers

LOG = logging.getLogger(__name__)
_INSTALLED = False
_DUMP_LOCK = threading.Lock()


def _dump_message_binary_safe(topic, payload) -> None:
    """Append raw MQTT messages to one JSONL file while preserving payload bytes."""
    try:
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise TypeError("payload must be bytes-like")

        raw = bytes(payload)
        root = os.path.abspath(grobro_client_module.DUMP_DIR)
        os.makedirs(root, exist_ok=True)
        file_path = os.path.abspath(os.path.join(root, "messages.jsonl"))
        if os.path.commonpath([root, file_path]) != root:
            raise ValueError("resolved dump path escaped DUMP_DIR")

        record = {
            "captured_at_ms": int(time.time() * 1000),
            "topic": str(topic),
            "payload_length": len(raw),
            "payload_encoding": "base64",
            "payload_base64": base64.b64encode(raw).decode("ascii"),
        }
        line = json.dumps(record, separators=(",", ":"))

        with _DUMP_LOCK, open(file_path, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")
    except (OSError, TypeError, ValueError) as exc:
        LOG.error("Failed to dump message for topic %s: %s", topic, exc)


def _validate_device_id(device_id: str) -> bytes:
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("device_id must be a non-empty string")
    try:
        raw = device_id.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("device_id must be ASCII") from exc
    if len(raw) > 16:
        raise ValueError("config-message device_id exceeds 16 bytes")
    return raw.ljust(16, b"\x00")


def _validate_register_no(register_no: int) -> int:
    if isinstance(register_no, bool) or not isinstance(register_no, int):
        raise ValueError("register_no must be an integer")
    if not 0 <= register_no <= 0xFFFF:
        raise ValueError("register_no must be between 0 and 65535")
    return register_no


def _publish_checked(client, topic: str, payload, **kwargs):
    return grobro_client_module._publish_checked(client, topic, payload, **kwargs)


def _build_config_packet(device_id: str, register_no: int, msg_type: int, body: bytes) -> bytes:
    dev = _validate_device_id(device_id)
    _validate_register_no(register_no)
    payload = b"\x00" * 14 + body
    msg_len = len(payload) + 18
    raw = (
        b"\x00\x01\x00\x07"
        + struct.pack(">H", msg_len)
        + struct.pack(">H", msg_type)
        + dev
        + payload
    )
    return append_crc(scramble(raw))


def _build_config_read_message(device_id: str, register_no: int) -> bytes:
    register_no = _validate_register_no(register_no)
    return _build_config_packet(
        device_id,
        register_no,
        0x0119,
        struct.pack(">HH", 1, register_no),
    )


def _build_config_write_message(device_id: str, register_no: int, value: str) -> bytes:
    register_no = _validate_register_no(register_no)
    value = str(value)
    try:
        value_bytes = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("config values must be ASCII") from exc
    if len(value_bytes) > 0xFFFF - 4:
        raise ValueError("config value is too long")

    tlv = (
        struct.pack(">HHHH", 1, len(value_bytes) + 4, register_no, len(value_bytes))
        + value_bytes
    )
    return _build_config_packet(device_id, register_no, 0x0118, tlv)


def install_grobro_cleanup_hook() -> None:
    """Install only fork-specific runtime features before clients are created."""
    global _INSTALLED
    if _INSTALLED:
        return

    client_cls = grobro_client_module.Client

    # Central family registry is the active register-map source for every family.
    grobro_client_module._known_registers_for_device = get_known_registers

    # Raw diagnostics use one append-only file instead of thousands of .bin files.
    grobro_client_module.dump_message_binary = _dump_message_binary_safe

    def send_config_read_clean(self, device_id: str, register_no: int):
        payload = _build_config_read_message(device_id, register_no)
        topic = f"s/33/{device_id}"
        LOG.info("Sending config read to %s register=%s", device_id, register_no)
        return _publish_checked(
            self._client,
            topic,
            payload,
            properties=grobro_client_module.MQTT_PROP_FORWARD_HA,
        )

    def send_config_clean(self, device_id: str, register_no: int, value: str):
        payload = _build_config_write_message(device_id, register_no, value)
        topic = f"s/33/{device_id}"
        LOG.info("Sending config message to %s register=%s", device_id, register_no)
        return _publish_checked(
            self._client,
            topic,
            payload,
            properties=grobro_client_module.MQTT_PROP_FORWARD_HA,
        )

    client_cls.send_config_read_message = send_config_read_clean
    client_cls.send_config_message = send_config_clean
    _INSTALLED = True
    LOG.info("Installed GroBro fork runtime layer")
