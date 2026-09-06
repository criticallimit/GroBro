"""Passive decoders for NOAH MQTT control/config traffic.

These helpers only interpret packets already captured by GroBro. They do not
send MQTT messages, read registers, or write device settings.
"""

from __future__ import annotations

import struct


def _device_id(data: bytes) -> str:
    if len(data) < 24:
        return ""
    return data[8:24].rstrip(b"\x00").decode("ascii", errors="replace")


def decode_0105(data: bytes) -> dict | None:
    """Decode NOAH single holding-register read request/response (0x0105)."""
    if len(data) < 44 or struct.unpack_from(">H", data, 6)[0] != 0x0105:
        return None
    register_no = struct.unpack_from(">H", data, 38)[0]
    echoed_register = struct.unpack_from(">H", data, 40)[0]
    result = {
        "message_type": "0x0105",
        "operation": "holding_register_read",
        "device_id": _device_id(data),
        "register": register_no,
        "echoed_register": echoed_register,
    }
    # Requests are 44 bytes including the two-byte protocol trailer. Responses
    # observed from real NOAH hardware add a 16-bit register value before it.
    if len(data) >= 46:
        result["kind"] = "response"
        result["value"] = struct.unpack_from(">H", data, 42)[0]
    else:
        result["kind"] = "request"
    return result


def decode_0106(data: bytes) -> dict | None:
    """Decode NOAH single holding-register write request/ack (0x0106)."""
    if len(data) < 44 or struct.unpack_from(">H", data, 6)[0] != 0x0106:
        return None
    register_no = struct.unpack_from(">H", data, 38)[0]
    value = struct.unpack_from(">H", data, 40)[0]
    result = {
        "message_type": "0x0106",
        "operation": "holding_register_write",
        "device_id": _device_id(data),
        "register": register_no,
        "value": value,
    }
    # Real acknowledgements contain one extra status byte before the trailer.
    if len(data) >= 45:
        result["kind"] = "ack"
        result["status"] = data[42]
    else:
        result["kind"] = "request"
    return result


def decode_0118(data: bytes) -> dict | None:
    """Decode Growatt cloud/device config-write packet (0x0118)."""
    if len(data) < 46 or struct.unpack_from(">H", data, 6)[0] != 0x0118:
        return None
    # After the 16-byte device id there are 14 reserved bytes, followed by a
    # TLV: config_type, TLV length, register number, value length, value.
    offset = 38
    if offset + 8 > len(data) - 2:
        return None
    config_type, tlv_len, register_no, value_len = struct.unpack_from(">HHHH", data, offset)
    value_start = offset + 8
    value_end = value_start + value_len
    if value_len < 0 or value_end > len(data) - 2:
        return None
    raw_value = data[value_start:value_end]
    try:
        value = raw_value.decode("ascii")
        value_encoding = "ascii"
    except UnicodeDecodeError:
        value = raw_value.hex()
        value_encoding = "hex"
    return {
        "message_type": "0x0118",
        "operation": "config_write",
        "kind": "command",
        "device_id": _device_id(data),
        "config_type": config_type,
        "tlv_length": tlv_len,
        "register": register_no,
        "value_length": value_len,
        "value": value,
        "value_encoding": value_encoding,
    }


def decode_interesting_noah_packet(data: bytes | None) -> dict | None:
    """Return a compact interpretation for control packets we are studying."""
    if not data or len(data) < 8:
        return None
    msg_type = struct.unpack_from(">H", data, 6)[0]
    if msg_type == 0x0105:
        return decode_0105(data)
    if msg_type == 0x0106:
        return decode_0106(data)
    if msg_type == 0x0118:
        return decode_0118(data)
    return None
