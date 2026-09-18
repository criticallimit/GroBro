"""Validated NOAH heater-state decoding from cyclic 0x0104 packets."""

from __future__ import annotations

import struct

from grobro import model
from grobro.grobro import parser

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


def heater_state_from_packet(payload, device_id: str) -> str | None:
    """Return the validated NOAH heater state from a cyclic status packet.

    Only NOAH devices and message type ``0x0104`` are accepted. Values outside
    the established 0..15 stack heater bitmask are intentionally rejected rather
    than guessed.
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


# Keep the hook beside the validated decoder; the two pieces form one feature.
import logging

from grobro.grobro import client as grobro_client_module

LOG = logging.getLogger(__name__)
_INSTALLED = False


def install_noah_heater_hook() -> None:
    """Install the validated NOAH heater telemetry override exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return

    client_cls = grobro_client_module.Client
    original_on_message = client_cls._Client__on_message

    def on_message_with_heater(self, client, userdata, msg):
        device_id = grobro_client_module._extract_device_id(getattr(msg, "topic", ""))
        heater_state = heater_state_from_packet(getattr(msg, "payload", None), device_id)
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

    client_cls._Client__on_message = on_message_with_heater
    _INSTALLED = True
    LOG.info("Installed validated NOAH heater compatibility hook")
