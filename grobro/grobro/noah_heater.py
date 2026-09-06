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
