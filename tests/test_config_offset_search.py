import random
from pathlib import Path

from grobro.grobro import parser


def reference(data):
    for offset in range(0x1C, len(data) - 4):
        key = int.from_bytes(data[offset:offset + 2], "big")
        length = int.from_bytes(data[offset + 2:offset + 4], "big")
        if 0 < key < 1000 and 0 < length < 256:
            return offset
    return 0x1C


def test_offset_search_matches_fixture_and_random_buffers():
    rng = random.Random(20261002)
    packets = [rng.randbytes(size) for size in range(600)]
    for path in (Path(__file__).parent / "model" / "data").glob("*.bin"):
        raw = path.read_bytes()
        packets.extend((raw, parser.unscramble(raw)))
    packets.extend((bytes(8192), bytes(28) + b"\x00\x04\x00\x01x"))
    for packet in packets:
        assert parser.find_config_offset(packet) == reference(packet)
        assert parser.find_config_offset(bytearray(packet)) == reference(packet)
