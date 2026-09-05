import struct

import crc

from grobro.grobro import parser
from grobro.grobro.builder import append_crc, hexdump, scramble

crc16 = crc.Calculator(crc.Crc16.MODBUS)


def test_scramble_roundtrip():
    original = b"\x00\x01\x00\x07\x00\x10\x01\x18" + b"ABCDEFGHIJ" + b"\x00" * 10
    scrambled = scramble(original)
    assert scrambled != original
    assert len(scrambled) == len(original)
    assert scrambled[:8] == original[:8]
    assert parser.unscramble(scrambled) == original


def test_scramble_unscramble_roundtrip_across_packet_sizes():
    for size in (0, 1, 7, 8, 9, 15, 64, 839, 2048):
        original = bytes((index * 37 + 11) & 0xFF for index in range(size))
        scrambled = scramble(original)
        assert len(scrambled) == len(original)
        assert scrambled[:8] == original[:8]
        assert parser.unscramble(scrambled) == original


def test_append_crc():
    pkt = b"test data"
    result = append_crc(pkt)
    assert len(result) == len(pkt) + 2
    stored_crc = struct.unpack("!H", result[-2:])[0]
    assert stored_crc == crc16.checksum(pkt)


def test_hexdump(capsys):
    data = b"Hello\x00World\xff"
    hexdump(data)
    captured = capsys.readouterr()
    assert "48 65 6C 6C 6F" in captured.out
    assert "Hello.World" in captured.out or "Hello.World." in captured.out
