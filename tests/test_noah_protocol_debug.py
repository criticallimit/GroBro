import struct

from grobro.grobro.noah_protocol_debug import (
    decode_0105,
    decode_0106,
    decode_0118,
    decode_interesting_noah_packet,
)


def _base_packet(msg_type: int, size: int = 48) -> bytearray:
    data = bytearray(size)
    data[0:4] = b"\x00\x01\x00\x07"
    struct.pack_into(">H", data, 6, msg_type)
    data[8:24] = b"0PVPTESTDEVICE01"
    return data


def test_decode_0105_request_and_response():
    request = _base_packet(0x0105, 44)
    struct.pack_into(">H", request, 38, 257)
    struct.pack_into(">H", request, 40, 257)
    decoded = decode_0105(bytes(request))
    assert decoded["kind"] == "request"
    assert decoded["register"] == 257
    assert decoded["echoed_register"] == 257

    response = _base_packet(0x0105, 46)
    struct.pack_into(">H", response, 38, 257)
    struct.pack_into(">H", response, 40, 257)
    struct.pack_into(">H", response, 42, 400)
    decoded = decode_0105(bytes(response))
    assert decoded["kind"] == "response"
    assert decoded["value"] == 400
    assert decoded["device_id"].startswith("0PVP")


def test_decode_0105_rejects_wrong_packets():
    assert decode_0105(b"short") is None
    packet = _base_packet(0x0106, 44)
    assert decode_0105(bytes(packet)) is None


def test_decode_0106_request_and_ack():
    request = _base_packet(0x0106, 44)
    struct.pack_into(">H", request, 38, 257)
    struct.pack_into(">H", request, 40, 800)
    decoded = decode_0106(bytes(request))
    assert decoded["kind"] == "request"
    assert decoded["register"] == 257
    assert decoded["value"] == 800

    ack = _base_packet(0x0106, 45)
    struct.pack_into(">H", ack, 38, 257)
    struct.pack_into(">H", ack, 40, 800)
    ack[42] = 1
    decoded = decode_0106(bytes(ack))
    assert decoded["kind"] == "ack"
    assert decoded["status"] == 1


def test_decode_0106_rejects_wrong_packets():
    assert decode_0106(b"short") is None
    packet = _base_packet(0x0105, 44)
    assert decode_0106(bytes(packet)) is None


def test_decode_0118_ascii_and_hex_values():
    packet = _base_packet(0x0118, 70)
    value = b"2026-09-06 16:09:43"
    struct.pack_into(">HHHH", packet, 38, 1, len(value) + 4, 31, len(value))
    packet[46 : 46 + len(value)] = value
    decoded = decode_0118(bytes(packet))
    assert decoded["register"] == 31
    assert decoded["value"] == value.decode()
    assert decoded["value_encoding"] == "ascii"

    packet = _base_packet(0x0118, 52)
    raw = b"\xff\x00"
    struct.pack_into(">HHHH", packet, 38, 1, len(raw) + 4, 99, len(raw))
    packet[46:48] = raw
    decoded = decode_0118(bytes(packet))
    assert decoded["value"] == "ff00"
    assert decoded["value_encoding"] == "hex"


def test_decode_0118_rejects_invalid_packets():
    assert decode_0118(b"short") is None
    wrong = _base_packet(0x0105, 48)
    assert decode_0118(bytes(wrong)) is None

    truncated_value = _base_packet(0x0118, 48)
    struct.pack_into(">HHHH", truncated_value, 38, 1, 20, 31, 20)
    assert decode_0118(bytes(truncated_value)) is None


def test_decode_interesting_noah_packet_dispatch():
    assert decode_interesting_noah_packet(None) is None
    assert decode_interesting_noah_packet(b"short") is None

    unknown = _base_packet(0x9999, 44)
    assert decode_interesting_noah_packet(bytes(unknown)) is None

    read_packet = _base_packet(0x0105, 44)
    struct.pack_into(">H", read_packet, 38, 257)
    struct.pack_into(">H", read_packet, 40, 257)
    assert decode_interesting_noah_packet(bytes(read_packet))["operation"] == "holding_register_read"

    write_packet = _base_packet(0x0106, 44)
    struct.pack_into(">H", write_packet, 38, 257)
    struct.pack_into(">H", write_packet, 40, 400)
    assert decode_interesting_noah_packet(bytes(write_packet))["operation"] == "holding_register_write"
