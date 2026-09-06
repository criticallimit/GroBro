import crc
import struct

crc16 = crc.Calculator(crc.Crc16.MODBUS)
_SCRAMBLE_MASK = b"Growatt"
_SCRAMBLE_MASK_LEN = len(_SCRAMBLE_MASK)
_CONFIG_HEADER = b"\x00\x01\x00\x07"
_CONFIG_READ_TYPE = 0x0119
_CONFIG_WRITE_TYPE = 0x0118


def scramble(pkt: bytes) -> bytes:
    """Apply Growatt's repeating XOR mask after the unchanged 8-byte header."""
    out = bytearray(pkt)
    mask_index = 0
    for index in range(8, len(out)):
        out[index] ^= _SCRAMBLE_MASK[mask_index]
        mask_index += 1
        if mask_index == _SCRAMBLE_MASK_LEN:
            mask_index = 0
    return bytes(out)


def append_crc(pkt: bytes) -> bytes:
    csum = crc16.checksum(pkt)
    return pkt + struct.pack("!H", csum)


def _config_device_field(device_id: str) -> bytes:
    """Encode the fixed-width 16-byte Growatt config device field."""
    encoded = str(device_id).encode("ascii")
    if len(encoded) > 16:
        raise ValueError("Growatt config device id exceeds 16 ASCII bytes")
    return encoded.ljust(16, b"\x00")


def _finalize_config_packet(message_type: int, device_id: str, payload: bytes) -> bytes:
    """Build, scramble and CRC-wrap one Growatt configuration packet."""
    message_length = len(payload) + 18
    raw = (
        _CONFIG_HEADER
        + struct.pack(">H", message_length)
        + struct.pack(">H", message_type)
        + _config_device_field(device_id)
        + payload
    )
    return append_crc(scramble(raw))


def build_config_read_packet(device_id: str, register_no: int) -> bytes:
    """Build a final Growatt 0x0119 single config-register read packet."""
    if not 0 <= int(register_no) <= 0xFFFF:
        raise ValueError("config register number must fit uint16")
    payload = b"\x00" * 14 + struct.pack(">HH", 1, int(register_no))
    return _finalize_config_packet(_CONFIG_READ_TYPE, device_id, payload)


def build_config_write_packet(device_id: str, register_no: int, value: str) -> bytes:
    """Build a final Growatt 0x0118 config-register write packet."""
    if not 0 <= int(register_no) <= 0xFFFF:
        raise ValueError("config register number must fit uint16")
    value_bytes = str(value).encode("ascii")
    if len(value_bytes) > 0xFFFF - 4:
        raise ValueError("config value is too large")

    tlv = (
        struct.pack(">H", 1)
        + struct.pack(">H", len(value_bytes) + 4)
        + struct.pack(">H", int(register_no))
        + struct.pack(">H", len(value_bytes))
        + value_bytes
    )
    payload = b"\x00" * 14 + tlv
    return _finalize_config_packet(_CONFIG_WRITE_TYPE, device_id, payload)


def hexdump(data: bytes, width: int = 16) -> None:
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        asc_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        print(f"{i:08X}  {hex_part:<{width * 3}} |{asc_part}|")
