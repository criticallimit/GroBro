"""Narrow runtime fixes for the Growatt-side MQTT client.

The compatibility layer keeps normal GroBro message/entity behavior intact while
fixing legacy state sharing and applying the cloud configuration filter in the
correct Cloud -> device direction.
"""

from __future__ import annotations

import logging
import struct

from grobro.grobro import client as grobro_client_module
from grobro.grobro import parser

LOG = logging.getLogger(__name__)
_INSTALLED = False

# Growatt configuration/control message types that must not be delivered from the
# cloud to a local device when GROWATT_CLOUD_CONFIG_FILTER is enabled.
_BLOCKED_CLOUD_MESSAGE_TYPES = {
    0x0118,  # config write
    0x0110,  # preset-multiple/config command family used by NOAH/NEXA
}


def _is_blocked_cloud_config_message(payload: bytes) -> bool:
    """Return True when a cloud payload is a filtered configuration command."""
    try:
        decoded = parser.unscramble(payload)
        if len(decoded) < 8:
            return False
        msg_type = struct.unpack_from(">H", decoded, 6)[0]
        return msg_type in _BLOCKED_CLOUD_MESSAGE_TYPES
    except (struct.error, TypeError, ValueError):
        # A malformed packet should not be treated as a known config write here;
        # the normal downstream parser/handling path can decide what to do with it.
        return False


def install_grobro_cleanup_hook() -> None:
    """Install Growatt-side fixes once before Client instances are created."""
    global _INSTALLED
    if _INSTALLED:
        return

    client_cls = grobro_client_module.Client

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
            grobro_client_module.GROWATT_CLOUD_CONFIG_FILTER == "true"
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
