from pathlib import Path

from grobro.grobro import parser
from grobro.grobro.noah_0103 import find_embedded_register_block

DATA_DIR = Path(__file__).parent / "model" / "data"


def test_real_noah_0103_contains_holding_register_block_250_374():
    raw = (DATA_DIR / "NoahType0103_HoldingRegs.bin").read_bytes()
    decoded = parser.unscramble(raw)

    block = find_embedded_register_block(decoded)

    assert block is not None
    assert block.start == 250
    assert block.end == 374
    assert len(block.values) == 125
    registers = block.registers
    assert registers[250] == 100
    assert registers[251] == 20
