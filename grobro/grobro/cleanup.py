"""Narrow runtime fixes for the Growatt-side MQTT client.

The compatibility layer keeps normal GroBro message/entity behavior intact while
fixing legacy state sharing, cloud-filter direction, defensive MQTT handling, and
safe diagnostic output.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import struct
import threading
import time

from grobro.grobro import client as grobro_client_module
from grobro.grobro import parser
from grobro.grobro.builder import append_crc, scramble

LOG = logging.getLogger(__name__)
_INSTALLED = False
_DUMP_LOCK = threading.Lock()

# Capture the user's configured intent before neutralizing the legacy check in
# the wrong (device -> cloud) forwarding direction.
_CLOUD_CONFIG_FILTER_ENABLED = (
    grobro_client_module.GROWATT_CLOUD_CONFIG_FILTER == "true"
)

# Growatt configuration/control message types that must not be delivered from the
# cloud to a local device when GROWATT_CLOUD_CONFIG_FILTER is enabled.
_BLOCKED_CLOUD_MESSAGE_TYPES = {
    0x0118,  # config write
    0x0110,  # preset-multiple/config command family used by NOAH/NEXA
}

_SAFE_TOPIC_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
_CONFIG_VALUE_LOG_RE = re.compile(r"(\bvalue=)(.*)$", re.IGNORECASE)


def _is_blocked_cloud_config_message(payload: bytes) -> bool:
    """Return True when a cloud payload is a filtered configuration command."""
    try:
        decoded = parser.unscramble(payload)
        if len(decoded) < 8:
            return False
        msg_type = struct.unpack_from(">H", decoded, 6)[0]
        return msg_type in _BLOCKED_CLOUD_MESSAGE_TYPES
    except (struct.error, TypeError, ValueError):
        return False


def _safe_topic_segment(segment: str) -> str:
    """Convert one MQTT topic level to a harmless filesystem component."""
    cleaned = _SAFE_TOPIC_SEGMENT_RE.sub("_", str(segment)).strip(".")
    if not cleaned or cleaned in {".", ".."}:
        return "_"
    return cleaned[:128]


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

        timestamp_ms = int(time.time() * 1000)
        record = {
            "captured_at_ms": timestamp_ms,
            "topic": str(topic),
            "payload_length": len(raw),
            "payload_encoding": "base64",
            "payload_base64": base64.b64encode(raw).decode("ascii"),
        }

        line = json.dumps(record, separators=(",", ":"))
        with _DUMP_LOCK:
            with open(file_path, "a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
    except (OSError, TypeError, ValueError) as exc:
        LOG.error("Failed to dump message for topic %s: %s", topic, exc)


def _get_property_safe(msg, prop) -> str | None:
    """Read an MQTT v5 UserProperty defensively."""
    properties = getattr(msg, "properties", None)
    if properties is None:
        return None
    try:
        data = properties.json()
    except (AttributeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    entries = data.get("UserProperty", []) or []
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            continue
        key, value = entry
        if key == prop:
            return value
    return None


def _validate_device_id(device_id: str) -> bytes:
    """Validate a config-message device id and return its padded wire form."""
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
    """Publish and warn immediately when Paho rejects the request locally."""
    result = client.publish(topic, payload, **kwargs)
    status = getattr(result, "rc", None)
    if status is None:
        try:
            status = result[0]
        except (TypeError, IndexError, KeyError):
            status = None
    if status not in (None, 0):
        LOG.warning("MQTT publish failed for topic %s: rc=%s", topic, status)
    return result


def _build_config_read_message(device_id: str, register_no: int) -> bytes:
    dev = _validate_device_id(device_id)
    register_no = _validate_register_no(register_no)
    payload = b"\x00" * 14 + struct.pack(">HH", 1, register_no)
    msg_len = len(payload) + 18
    raw = (
        b"\x00\x01\x00\x07"
        + struct.pack(">H", msg_len)
        + struct.pack(">H", 0x0119)
        + dev
        + payload
    )
    return append_crc(scramble(raw))


def _build_config_write_message(device_id: str, register_no: int, value: str) -> bytes:
    dev = _validate_device_id(device_id)
    register_no = _validate_register_no(register_no)
    if not isinstance(value, str):
        value = str(value)
    try:
        value_bytes = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("config values must be ASCII") from exc
    if len(value_bytes) > 0xFFFF - 4:
        raise ValueError("config value is too long")

    tlv = (
        struct.pack(">H", 1)
        + struct.pack(">H", len(value_bytes) + 4)
        + struct.pack(">H", register_no)
        + struct.pack(">H", len(value_bytes))
        + value_bytes
    )
    payload = b"\x00" * 14 + tlv
    msg_len = len(payload) + 18
    raw = (
        b"\x00\x01\x00\x07"
        + struct.pack(">H", msg_len)
        + struct.pack(">H", 0x0118)
        + dev
        + payload
    )
    return append_crc(scramble(raw))


class _ConfigValueRedactionFilter(logging.Filter):
    """Prevent config values/credentials from leaking through legacy log calls."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            template = str(record.msg)
            if "config read response" in template.lower() and isinstance(record.args, tuple):
                if len(record.args) >= 3:
                    record.args = (*record.args[:-1], "<redacted>")
            elif "sending config message" in template.lower():
                rendered = record.getMessage()
                record.msg = _CONFIG_VALUE_LOG_RE.sub(r"\1<redacted>", rendered)
                record.args = ()
        except Exception:
            # A logging filter must never break message processing.
            return True
        return True


def _install_log_redaction_filter() -> None:
    logger = grobro_client_module.LOG
    if any(isinstance(existing, _ConfigValueRedactionFilter) for existing in logger.filters):
        return
    logger.addFilter(_ConfigValueRedactionFilter())


def install_grobro_cleanup_hook() -> None:
    """Install Growatt-side fixes once before Client instances are created."""
    global _INSTALLED
    if _INSTALLED:
        return

    client_cls = grobro_client_module.Client

    # The upstream implementation applies GROWATT_CLOUD_CONFIG_FILTER while
    # forwarding device-originated packets TO the cloud. That is the opposite of
    # the documented protection goal. Disable only that legacy direction here;
    # the wrapper below enforces the captured setting on Cloud -> device traffic.
    grobro_client_module.GROWATT_CLOUD_CONFIG_FILTER = "false"

    # Harden global helpers used by both the local and forwarding callbacks.
    grobro_client_module.dump_message_binary = _dump_message_binary_safe
    grobro_client_module.get_property = _get_property_safe
    _install_log_redaction_filter()

    # Upstream stores forward clients on the class, which shares connections
    # across instances/tests. Keep them per instance instead.
    original_init = client_cls.__init__

    def init_clean(self, *args, **kwargs):
        self._forward_clients = {}
        return original_init(self, *args, **kwargs)

    client_cls.__init__ = init_clean

    def stop_clean(self):
        """Stop all MQTT loops best-effort and discard stale forward clients."""
        try:
            self._client.loop_stop()
        finally:
            try:
                self._client.disconnect()
            except Exception as exc:  # network teardown must remain best-effort
                LOG.debug("Primary MQTT disconnect failed during shutdown: %s", exc)

        clients = list(getattr(self, "_forward_clients", {}).values())
        for forward_client in clients:
            try:
                forward_client.loop_stop()
            except Exception as exc:
                LOG.debug("Forward MQTT loop_stop failed during shutdown: %s", exc)
            try:
                forward_client.disconnect()
            except Exception as exc:
                LOG.debug("Forward MQTT disconnect failed during shutdown: %s", exc)
        self._forward_clients.clear()

    client_cls.stop = stop_clean

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

    client_cls.send_config_read_message = send_config_read_clean

    def send_config_clean(self, device_id: str, register_no: int, value: str):
        payload = _build_config_write_message(device_id, register_no, value)
        topic = f"s/33/{device_id}"
        # Deliberately never log the config value. Some registers contain
        # credentials and older versions could leak them into Home Assistant logs.
        LOG.info("Sending config message to %s register=%s", device_id, register_no)
        return _publish_checked(
            self._client,
            topic,
            payload,
            properties=grobro_client_module.MQTT_PROP_FORWARD_HA,
        )

    client_cls.send_config_message = send_config_clean

    original_forward_handler = client_cls._Client__on_message_forward_client

    def forward_handler_clean(self, client, userdata, msg):
        if (
            _CLOUD_CONFIG_FILTER_ENABLED
            and _is_blocked_cloud_config_message(msg.payload)
        ):
            device_id = grobro_client_module._extract_device_id(msg.topic)
            LOG.warning(
                "Blocked configuration command from Growatt Cloud for %s",
                device_id,
            )
            return
        return original_forward_handler(self, client, userdata, msg)

    client_cls._Client__on_message_forward_client = forward_handler_clean
    _INSTALLED = True
    LOG.info("Installed GroBro Growatt-side cleanup compatibility layer")
