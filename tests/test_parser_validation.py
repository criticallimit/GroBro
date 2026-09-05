import struct

import pytest

from grobro.grobro import parser


def test_config_read_rejects_truncated_packet():
    with pytest.raises(ValueError):
        parser.parse_config_message(b"\x00" * 20)


def test_config_ack_rejects_truncated_packet():
    with pytest.raises(ValueError):
        parser.parse_config_ack(b"\x00" * 20)


def test_noah_fe18_short_payload_returns_error():
    data = b"\x00\x01\x00\x07\x00\x10\xfe\x18" + b"\x00" * 20
    result = parser.parse_noah_fe18(data)
    assert result["message_type"] == 0xFE18
    assert "error" in result


def test_noah_0125_short_payload_returns_error():
    data = b"\x00\x01\x00\x07\x00\x10\x01\x25" + b"\x00" * 20
    result = parser.parse_noah_0125(data)
    assert result["message_type"] == 0x0125
    assert "error" in result


def test_fe25_tiny_payload_does_not_use_negative_slice():
    data = b"\x00\x01\x00\x07\x00\x10\xfe\x25" + b"\x00" * 16
    result = parser.parse_noah_fe25(data)
    assert result["message_type"] == 0xFE25
    assert result["is_empty"] is True


def test_smart_meter_rejects_short_packet():
    result = parser.parse_noah_6f64(b"\x00" * 40)
    assert result["message_type"] == 0x6F64
    assert "error" in result


def test_smart_meter_rejects_json_length_past_packet_end():
    data = bytearray(81)
    data[6:8] = b"\x6f\x64"
    data[75:79] = struct.pack(">I", 100)
    result = parser.parse_noah_6f64(bytes(data))
    assert result["message_type"] == 0x6F64
    assert "error" in result
