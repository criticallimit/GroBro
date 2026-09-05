import crc
import struct

crc16 = crc.Calculator(crc.Crc16.MODBUS)
_SCRAMBLE_MASK = b"Growatt"
_SCRAMBLE_MASK_LEN = len(_SCRAMBLE_MASK)


def scramble(pkt: bytes) -> bytes:
    """Apply Growatt's repeating XOR mask after the unchanged 8-byte header."""
    out = bytearray(pkt)
    for index in range(8, len(out)):
        out[index] ^= _SCRAMBLE_MASK[(index - 8) % _SCRAMBLE_MASK_LEN]
    return bytes(out)


def append_crc(pkt: bytes) -> bytes:
    csum = crc16.checksum(pkt)
    return pkt + struct.pack("!H", csum)


def hexdump(data: bytes, width: int = 16) -> None:
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        asc_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        print(f"{i:08X}  {hex_part:<{width * 3}} |{asc_part}|")
