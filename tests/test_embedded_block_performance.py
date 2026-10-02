import random
import struct
from pathlib import Path

import pytest

from grobro.grobro import parser
from grobro.grobro.noah_0103 import find_embedded_register_block


def reference(packet):
    if len(packet) < 62:
        return None
    data = packet[54:-2]
    candidates = []
    for offset in range(len(data) - 5):
        start, end = struct.unpack_from(">HH", data, offset)
        count = end - start + 1
        if not 0 < count <= 2048 or offset + 4 + count * 2 != len(data):
            continue
        values = tuple(struct.unpack_from(">H", data, offset + 4 + 2 * i)[0] for i in range(count))
        candidates.append((offset, start, end, values))
    return max(candidates, key=lambda item: len(item[3]), default=None)


def assert_matches(packet):
    result = find_embedded_register_block(packet)
    actual = None if result is None else (result.offset, result.start, result.end, result.values)
    assert actual == reference(packet)


def test_fixture_packets_keep_identical_block_selection():
    for path in (Path(__file__).parent / "model" / "data").glob("*.bin"):
        packet = path.read_bytes()
        assert_matches(packet)
        assert_matches(parser.unscramble(packet))


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_random_and_embedded_packets_keep_identical_selection(seed):
    rng = random.Random(seed)
    for size in range(0, 600, 3):
        assert_matches(rng.randbytes(size))
    for count in range(1, 130):
        start = rng.randrange(0, 64000)
        prefix = rng.randbytes(rng.randrange(30))
        values = rng.randbytes(count * 2)
        packet = bytes(54) + prefix + struct.pack(">HH", start, start + count - 1) + values + b"xx"
        assert_matches(packet)
        assert_matches(bytearray(packet))


@pytest.mark.parametrize("count", [2048, 2049])
def test_candidate_limit_is_unchanged(count):
    assert_matches(bytes(54) + struct.pack(">HH", 0, count - 1) + bytes(count * 2) + b"xx")


def test_largest_candidate_wins_over_valid_suffix():
    packet = bytes(54) + struct.pack(">HH", 100, 105) + bytes(4) + struct.pack(">HHHH", 200, 201, 5, 6) + b"xx"
    assert_matches(packet)
    assert find_embedded_register_block(packet).start == 100
