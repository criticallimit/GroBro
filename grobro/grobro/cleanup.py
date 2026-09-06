"""Better GroBro fork-specific runtime helpers.

Core protocol handling, cloud filtering, config packet building, device-family
selection, MQTT property parsing and shutdown logic live in the hardened core.
This module intentionally contains only fork-specific runtime behavior that still
needs to observe/augment the core client: raw-dump compatibility wiring and the
validated NOAH status-frame heater compatibility fix.
"""

from __future__ import annotations

import logging
import struct

from grobro import model
from grobro.grobro import client as grobro_client_module
from grobro.grobro import parser
from grobro.grobro.raw_dump import dump_message_jsonl

LOG = logging.getLogger(__name__)
_INSTALLED = False

# Community-validated NOAH status frame (message type 260 / 0x0104): after
# descrambling, the status payload begins at byte 24 and heater state is byte 84
# within that payload. Thus the absolute offset is 108. Single-NOAH captures
# have repeatedly shown 0=off and 1=on. Values 0..15 are kept compatible with
# GroBro's existing stack heater bitmask labels so the existing HA entity and
# state vocabulary can be reused without creating a second Heater entity.
_NOAH_STATUS_MESSAGE_TYPE = 0x0104
_NOAH_STATUS_PAYLOAD_OFFSET = 24
_NOAH_HEATER_PAYLOAD_OFFSET = 84
_NOAH_HEATER_ABSOLUTE_OFFSET = _NOAH_STATUS_PAYLOAD_OFFSET + _NOAH_HEATER_PAYLOAD_OFFSET
_NOAH_HEATER_STATES = {
    0: "Off",
    1: "1 On",
    2: "2 On",
    3: "1&2 On",
    4: "3 On",
    5: "1&3 On",
    6: "2&3 On",
    7: "1&2&3 On",
    8: "4 On",
    9: "1&4 On",
    10: "2&4 On",
    11: "1&2&4 On",
    12: "3&4 On",
    13: "1&3&4 On",
    14: "2&3&4 On",
    15: "All On",
}


def _noah_heater_state_from_packet(payload, device_id: str) -> str | None:
    """Return the validated status-frame heater state for a NOAH packet.

    This deliberately does not guess values outside the existing 0..15 stack
    bitmask. If a future firmware emits a different encoding, the normal R17
    value remains as fallback until that new encoding is validated.
    """
    if not model.is_family(device_id, "noah"):
        return None
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        return None
    if len(payload) <= _NOAH_HEATER_ABSOLUTE_OFFSET:
        return None

    try:
        plain = parser.unscramble(bytes(payload))
        msg_type = struct.unpack_from(">H", plain, 6)[0]
        if msg_type != _NOAH_STATUS_MESSAGE_TYPE:
            return None
        raw_state = plain[_NOAH_HEATER_ABSOLUTE_OFFSET]
    except (struct.error, TypeError, ValueError):
        return None

    return _NOAH_HEATER_STATES.get(raw_state)


def _dump_message_binary_safe(topic, payload) -> None:
    """Compatibility wrapper around the centralized single-file raw dumper."""
    dump_message_jsonl(grobro_client_module.DUMP_DIR, topic, payload)


def install_grobro_cleanup_hook() -> None:
    """Install only fork-specific runtime behavior before clients are created."""
    global _INSTALLED
    if _INSTALLED:
        return

    client_cls = grobro_client_module.Client

    # Preserve the historical dump hook name while routing it to the centralized
    # append-only JSONL dumper. The client can later call raw_dump directly.
    grobro_client_module.dump_message_binary = _dump_message_binary_safe

    # Preserve the existing NOAH Heater HA entity, but replace its unreliable R17
    # state with the heater byte from the validated cyclic 0x0104 status frame.
    original_on_message = client_cls._Client__on_message

    def on_message_clean(self, client, userdata, msg):
        device_id = grobro_client_module._extract_device_id(getattr(msg, "topic", ""))
        heater_state = _noah_heater_state_from_packet(getattr(msg, "payload", None), device_id)
        original_input_callback = getattr(self, "on_input_register", None)

        if heater_state is None or not callable(original_input_callback):
            return original_on_message(self, client, userdata, msg)

        def input_register_with_heater(state):
            if state.device_id == device_id:
                state.payload["heater"] = heater_state
            return original_input_callback(state)

        self.on_input_register = input_register_with_heater
        try:
            return original_on_message(self, client, userdata, msg)
        finally:
            self.on_input_register = original_input_callback

    client_cls._Client__on_message = on_message_clean
    _INSTALLED = True
    LOG.info("Installed GroBro fork runtime layer")
