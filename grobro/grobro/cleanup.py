"""Narrow runtime fixes for the Growatt-side MQTT client.

The compatibility layer keeps normal GroBro message/entity behavior intact while
fixing legacy state sharing, cloud-filter direction, and defensive MQTT handling.
"""

from __future__ import annotations

import logging
import os
import re
import struct
import time

from grobro.grobro import client as grobro_client_module
from grobro.grobro import parser

LOG = logging.getLogger(__name__)
_INSTALLED = False

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
    """Write a binary MQTT dump without allowing topic-based path traversal."""
    try:
        topic_parts = [
            _safe_topic_segment(part)
            for part in str(topic).strip("/").split("/")
            if part != ""
        ]
        if not topic_parts:
            topic_parts = ["_"]

        root = os.path.abspath(grobro_client_module.DUMP_DIR)
        dir_path = os.path.abspath(os.path.join(root, *topic_parts))
        if os.path.commonpath([root, dir_path]) != root:
            raise ValueError("resolved dump path escaped DUMP_DIR")

        os.makedirs(dir_path, exist_ok=True)
        timestamp = int(time.time() * 1000)
        file_path = os.path.join(dir_path, f"{timestamp}.bin")
        with open(file_path, "wb") as handle:
            handle.write(payload)
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

    # Upstream stores forward clients on the class, which shares connections
    # across instances/tests. Keep them per instance instead.
    original_init = client_cls.__init__

    def init_clean(self, *args, **kwargs):
        self._forward_clients = {}
        return original_init(self, *args, **kwargs)

    client_cls.__init__ = init_clean

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
