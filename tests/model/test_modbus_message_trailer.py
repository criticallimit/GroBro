import struct
from pathlib import Path

from grobro.grobro import parser
from grobro.model.modbus_message import GrowattModbusFunction, GrowattModbusMessage

DATA_DIR = Path(__file__).parent / "data"


def test_real_noah_0_124_fixture_parses_with_two_byte_trailer():
    raw = (DATA_DIR / "NoahReadInputRegisters_0-124.bin").read_bytes()
    decoded = parser.unscramble(raw)

    message = GrowattModbusMessage.parse_grobro(decoded)

    assert message is not None
    assert message.function == GrowattModbusFunction.READ_INPUT_REGISTER
    assert message.register_blocks
    assert message.register_blocks[0].start == 0
    assert message.register_blocks[0].end == 124
    assert len(message.register_blocks[0].values) == 250


def _single_register_message(with_trailer: bool) -> bytes:
    device_id = b"TEST".ljust(30, b"\x00")
    block = struct.pack(">HHH", 123, 123, 456)
    trailer = b"\xaa\xbb" if with_trailer else b""
    total_len = 38 + len(block) + len(trailer)
    msg_len = total_len - 8
    header = struct.pack(">HHHBB30s", 1, 7, msg_len, 1, 3, device_id)
    return header + block + trailer


def test_final_single_register_without_trailer_is_parsed():
    message = GrowattModbusMessage.parse_grobro(_single_register_message(False))
    assert message is not None
    assert len(message.register_blocks) == 1
    assert message.register_blocks[0].start == 123
    assert message.register_blocks[0].end == 123


def test_final_single_register_with_trailer_is_parsed():
    message = GrowattModbusMessage.parse_grobro(_single_register_message(True))
    assert message is not None
    assert len(message.register_blocks) == 1
    assert message.register_blocks[0].start == 123
    assert message.register_blocks[0].end == 123
