# Parser and unscrambler for Growatt MQTT data packages.
# Automatically descrambles the binary data and decodes it into a structured format.

import logging
import struct

import grobro.model as model

LOG = logging.getLogger(__name__)
_SCRAMBLE_MASK = b"Growatt"
_SCRAMBLE_MASK_LEN = len(_SCRAMBLE_MASK)


def unscramble(decdata: bytes):
    """Unscramble Growatt payload bytes using the repeating ``Growatt`` mask."""
    # Growatt leaves the first eight protocol bytes unchanged and XORs every
    # following byte with the repeating ASCII mask. Mutating one bytearray avoids
    # the quadratic bytes concatenation and repeated hex/int conversions used by
    # the legacy implementation while remaining bit-for-bit identical.
    result = bytearray(decdata)
    mask_index = 0
    for index in range(8, len(result)):
        result[index] ^= _SCRAMBLE_MASK[mask_index]
        mask_index += 1
        if mask_index == _SCRAMBLE_MASK_LEN:
            mask_index = 0
    return bytes(result)


def parse_config_type(data, offset) -> model.DeviceConfig:
    """Parse a TLV configuration block starting at ``offset``."""
    config = {}
    end = len(data)
    raw_hex = data[offset:].hex()
    any_params = False

    param_map = {
        4: "data_interval",
        5: "unknown_5",
        6: "unknown_6",
        7: "password",
        8: "serial_number",
        9: "protocol_version",
        10: "unknown_10",
        11: "unknown_11",
        12: "dns_address",
        13: "device_type",
        14: "local_ip",
        15: "unknown_port",
        16: "mac_address",
        17: "remote_ip",
        18: "remote_port",
        19: "remote_url",
        20: "model_id",
        21: "sw_version",
        22: "hw_version",
        23: "unknown_23",
        24: "unknown_24",
        25: "subnet_mask",
        26: "default_gateway",
        27: "unknown_27",
        28: "unknown_28",
        29: "unknown_29",
        30: "timezone",
        31: "datetime",
        76: "wifi_signal",
    }

    max_len = 512

    while offset + 4 <= end:
        key_id = int.from_bytes(data[offset : offset + 2], "big")
        key_len = int.from_bytes(data[offset + 2 : offset + 4], "big")
        offset += 4

        if key_len == 0 or key_len > max_len or offset + key_len > end:
            break

        raw_val = data[offset : offset + key_len]
        offset += key_len

        try:
            val = raw_val.decode("ascii").strip("\x00")
            if any(ord(c) < 32 or ord(c) > 126 for c in val):
                raise ValueError()
        except (UnicodeDecodeError, ValueError):
            val = raw_val.hex()

        label = param_map.get(key_id, f"param_{key_id}")
        config[label] = val
        any_params = True

    if not any_params:
        config["raw"] = raw_hex

    return model.DeviceConfig(**config)


def find_config_offset(data):
    """Heuristically locate the start of a TLV configuration block."""
    for i in range(0x1C, len(data) - 4):
        key = int.from_bytes(data[i : i + 2], "big")
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if 0 < key < 1000 and 0 < length < 256:
            return i
    return 0x1C


def parse_config_message(data: bytes):
    config_read_struct = struct.Struct(">4sHH16s14sH1xH2x")
    if len(data) < config_read_struct.size + 2:
        raise ValueError("config read response is truncated")

    (
        header,
        msg_len,
        msg_type,
        device_id,
        _padding,
        config_type,
        register_no,
    ) = config_read_struct.unpack_from(data)

    # Remove the known two-byte protocol trailer/checksum.
    value = data[config_read_struct.size:-2].decode("ascii", errors="replace")

    return {
        "header": header,
        "message_length": msg_len,
        "message_type": msg_type,
        "device_id": device_id.rstrip(b"\x00").decode("ascii", errors="replace"),
        "config_type": config_type,
        "register_no": register_no,
        "value": value,
    }


def parse_config_ack(data: bytes):
    config_ack_struct = struct.Struct(">4sHH16s14sH")
    if len(data) < config_ack_struct.size:
        raise ValueError("config acknowledgement is truncated")

    (
        header,
        msg_len,
        msg_type,
        device_id,
        _padding,
        register_no,
    ) = config_ack_struct.unpack_from(data)

    return {
        "header": header,
        "message_length": msg_len,
        "message_type": msg_type,
        "device_id": device_id.rstrip(b"\x00").decode("ascii", errors="replace"),
        "register_no": register_no,
    }


# All NOAH-specific message types share a common payload structure:
#   14 zero bytes + type-specific data
# The 2-byte type/subtype field starts at payload offset 14.


def parse_noah_0103(data: bytes) -> dict:
    """Parse NOAH type 0x0103 as an address-unknown sequence of 16-bit values."""
    payload = data[24:]
    device_id = payload[14:30].rstrip(b"\x00").decode("ascii", errors="replace")
    reg_data = payload[30:]
    registers = []
    for i in range(0, len(reg_data) - 1, 2):
        registers.append(struct.unpack_from(">H", reg_data, i)[0])
    return {
        "message_type": 0x0103,
        "device_id": device_id,
        "registers": registers,
        "register_count": len(registers),
    }


def parse_noah_0110(data: bytes) -> dict:
    """Parse NOAH type 0x0110 preset-multiple response/ack."""
    payload = data[24:]
    regs = {}
    body = payload[14:]
    pos = 0
    while pos + 4 <= len(body):
        reg = struct.unpack_from(">H", body, pos)[0]
        val = struct.unpack_from(">H", body, pos + 2)[0]
        regs[reg] = val
        pos += 4
    return {
        "message_type": 0x0110,
        "device_id": data[8:24].rstrip(b"\x00").decode("ascii", errors="replace"),
        "registers": regs,
    }


def parse_noah_0125(data: bytes) -> dict:
    """Parse NOAH type 0x0125 serial-number query response."""
    payload = data[24:]
    if len(payload) < 30:
        return {"message_type": 0x0125, "device_id": "", "error": "payload too short"}
    device_id = payload[14:30].rstrip(b"\x00").decode("ascii", errors="replace")
    return {"message_type": 0x0125, "device_id": device_id}


def parse_noah_fe18(data: bytes) -> dict:
    """Parse NOAH type 0xFE18 datetime command."""
    payload = data[24:]
    if len(payload) < 18:
        return {"message_type": 0xFE18, "error": "payload too short"}

    sub_type = struct.unpack_from(">H", payload, 14)[0]
    tlv_len = struct.unpack_from(">H", payload, 16)[0]
    f1 = struct.unpack_from(">H", payload, 18)[0] if len(payload) >= 20 else 0
    f2 = struct.unpack_from(">H", payload, 20)[0] if len(payload) >= 22 else 0
    datetime_str = (
        payload[22:41].decode("ascii", errors="replace") if len(payload) >= 41 else ""
    )
    return {
        "message_type": 0xFE18,
        "device_id": data[8:24].rstrip(b"\x00").decode("ascii", errors="replace"),
        "subtype": sub_type,
        "tlv_length": tlv_len,
        "field_1": f1,
        "field_2": f2,
        "datetime": datetime_str,
    }


FE19_SUBTYPE_FULL_CONFIG = 0x0020
FE19_SUBTYPE_DEV_STATUS = 0x0001


def parse_noah_fe19(data: bytes) -> dict:
    """Parse NOAH type 0xFE19 configuration/status TLV message."""
    payload = data[24:]
    if len(payload) < 18:
        return {"message_type": 0xFE19, "error": "payload too short"}
    subtype = struct.unpack_from(">H", payload, 14)[0]
    tlv_offset = find_config_offset(payload)
    config = parse_config_type(payload, tlv_offset)
    return {
        "message_type": 0xFE19,
        "device_id": data[8:24].rstrip(b"\x00").decode("ascii", errors="replace"),
        "subtype": subtype,
        "config": config,
        "tlv_offset": tlv_offset,
    }


def parse_noah_fe25(data: bytes) -> dict:
    """Parse NOAH type 0xFE25 heartbeat/keepalive."""
    payload = data[24:]
    # Exclude the known tail when present; never allow a negative slice length.
    check_len = max(0, min(40, len(payload) - 4))
    payload_body = payload[:check_len]
    return {
        "message_type": 0xFE25,
        "device_id": data[8:24].rstrip(b"\x00").decode("ascii", errors="replace"),
        "payload_length": len(payload),
        "is_empty": all(b == 0 for b in payload_body),
    }


def parse_noah_6f64(data: bytes) -> dict:
    """Parse NOAH/NEXA type 0x6F64 smart-meter JSON data."""
    # 79 bytes fixed header + at least the 2-byte protocol trailer.
    if len(data) < 81:
        return {"message_type": 0x6F64, "error": "payload too short"}

    device_id = data[8:38].rstrip(b"\x00").decode("ascii", errors="replace")
    smart_meter_sn = data[38:68].rstrip(b"\x00").decode("ascii", errors="replace")
    year_b, month, day, hour, minute, second, millis = struct.unpack_from(
        ">BBBBBBB", data, 68
    )
    json_len = struct.unpack_from(">I", data, 75)[0]
    json_end = 79 + json_len
    if json_end > len(data) - 2:
        return {
            "message_type": 0x6F64,
            "device_id": device_id,
            "smart_meter_sn": smart_meter_sn,
            "error": "JSON payload length exceeds packet",
        }

    json_bytes = data[79:json_end]
    json_str = json_bytes.decode("ascii", errors="replace")
    return {
        "message_type": 0x6F64,
        "device_id": device_id,
        "smart_meter_sn": smart_meter_sn,
        "timestamp": (
            f"{2000 + year_b:04d}-{month:02d}-{day:02d}T"
            f"{hour:02d}:{minute:02d}:{second:02d}.{millis:03d}"
        ),
        "json_length": json_len,
        "data": json_str,
    }


NOAH_DECODERS = {
    0x0103: parse_noah_0103,
    0x0110: parse_noah_0110,
    0x0125: parse_noah_0125,
    0xFE18: parse_noah_fe18,
    0xFE19: parse_noah_fe19,
    0xFE25: parse_noah_fe25,
    0x6F64: parse_noah_6f64,
}


def parse_noah_message(data: bytes) -> dict | None:
    """Dispatch a NOAH message using the message type at offset 6."""
    if len(data) < 8:
        return None
    msg_type = struct.unpack_from(">H", data, 6)[0]
    decoder = NOAH_DECODERS.get(msg_type)
    if decoder:
        return decoder(data)
    return None