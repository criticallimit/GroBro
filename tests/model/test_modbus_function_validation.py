import struct

from grobro.model.modbus_function import (
    GrowattModbusFunctionMultiple,
    GrowattModbusFunctionSingle,
)


def test_single_rejects_short_packet():
    assert GrowattModbusFunctionSingle.parse_grobro(b"\x00" * 10) is None


def test_single_rejects_wrong_header_constants():
    packet = struct.pack(
        ">HHHBB30sHH",
        2,
        7,
        36,
        1,
        3,
        b"SN123".ljust(30, b"\x00"),
        10,
        10,
    )
    assert GrowattModbusFunctionSingle.parse_grobro(packet) is None


def test_single_rejects_trailing_data():
    packet = struct.pack(
        ">HHHBB30sHH",
        1,
        7,
        37,
        1,
        3,
        b"SN123".ljust(30, b"\x00"),
        10,
        10,
    ) + b"\x00"
    assert GrowattModbusFunctionSingle.parse_grobro(packet) is None


def test_multiple_rejects_truncated_preset_values():
    packet = struct.pack(
        ">HHHBB30sHH",
        1,
        7,
        38,
        1,
        16,
        b"SN123".ljust(30, b"\x00"),
        100,
        101,
    ) + struct.pack(">H", 1)
    assert GrowattModbusFunctionMultiple.parse_grobro(packet) is None


def test_multiple_rejects_reverse_range():
    packet = struct.pack(
        ">HHHBB30sHH",
        1,
        7,
        36,
        1,
        3,
        b"SN123".ljust(30, b"\x00"),
        101,
        100,
    )
    assert GrowattModbusFunctionMultiple.parse_grobro(packet) is None
