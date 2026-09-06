import struct

import pytest

from grobro.grobro.builder import (
    append_crc,
    build_config_read_packet,
    build_config_write_packet,
    scramble,
)


def _decode_wire_packet(packet: bytes) -> bytes:
    # CRC covers the scrambled message. Applying the XOR again restores raw data.
    assert append_crc(packet[:-2]) == packet
    return scramble(packet[:-2])


def test_build_config_read_packet_matches_0119_wire_format():
    raw = _decode_wire_packet(build_config_read_packet("0PVPTEST", 31))

    assert raw[:4] == b"\x00\x01\x00\x07"
    assert struct.unpack_from(">H", raw, 6)[0] == 0x0119
    assert raw[8:24].rstrip(b"\x00") == b"0PVPTEST"
    assert raw[24:38] == b"\x00" * 14
    assert struct.unpack_from(">HH", raw, 38) == (1, 31)
    assert struct.unpack_from(">H", raw, 4)[0] == len(raw) - 6


def test_build_config_write_packet_matches_0118_wire_format():
    raw = _decode_wire_packet(build_config_write_packet("0PVPTEST", 31, "2026-09-06 18:00:00"))

    assert raw[:4] == b"\x00\x01\x00\x07"
    assert struct.unpack_from(">H", raw, 6)[0] == 0x0118
    assert raw[8:24].rstrip(b"\x00") == b"0PVPTEST"
    assert raw[24:38] == b"\x00" * 14

    count, tlv_length, register_no, value_length = struct.unpack_from(">HHHH", raw, 38)
    assert count == 1
    assert register_no == 31
    value = raw[46 : 46 + value_length]
    assert value == b"2026-09-06 18:00:00"
    assert tlv_length == value_length + 4
    assert struct.unpack_from(">H", raw, 4)[0] == len(raw) - 6


@pytest.mark.parametrize("register_no", [-1, 0x10000])
def test_config_packet_builders_reject_invalid_registers(register_no):
    with pytest.raises(ValueError):
        build_config_read_packet("0PVPTEST", register_no)
    with pytest.raises(ValueError):
        build_config_write_packet("0PVPTEST", register_no, "1")


def test_config_packet_builders_reject_long_device_ids():
    with pytest.raises(ValueError):
        build_config_read_packet("ABCDEFGHIJKLMNOPQ", 31)


def test_config_write_rejects_non_ascii_values():
    with pytest.raises(UnicodeEncodeError):
        build_config_write_packet("0PVPTEST", 31, "ä")
