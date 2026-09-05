import struct
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from grobro.model.modbus_message import GrowattModbusFunction

MODBUS_COMMAND_STRUCT = ">HHHBB30sHH"
MODBUS_COMMAND_SIZE = struct.calcsize(MODBUS_COMMAND_STRUCT)


def _unpack_command_header(buffer: bytes):
    """Return the common command tuple or None for malformed data."""
    if len(buffer) < MODBUS_COMMAND_SIZE:
        return None
    try:
        values = struct.unpack(MODBUS_COMMAND_STRUCT, buffer[:MODBUS_COMMAND_SIZE])
    except struct.error:
        return None

    header_id, constant_7, msg_len, device_address, function, *_ = values
    if header_id != 1 or constant_7 != 7 or device_address != 1:
        return None
    # Command messages encode length as total packet length minus the first
    # three 16-bit header fields (6 bytes).
    if msg_len != len(buffer) - 6:
        return None
    if function not in [entry.value for entry in GrowattModbusFunction]:
        return None
    return values


class GrowattModbusFunctionMultiple(BaseModel):
    """
    Represents a message that can be sent to the inverter
    to read or write multiple registers.

    Structure:
        - H - 2 byte header id
        - H - 2 byte constant 7
        - H - 2 byte message length
        - B - 1 byte modbus device address (normally 1 in MQTT)
        - B - 1 byte function
        - 30s - 30 byte zero-padded device id
        - H - 2 byte start register
        - H - 2 byte end register
        - N x H - N 16-bit values (when present)
    """

    device_id: str
    function: GrowattModbusFunction
    start: int
    end: int
    values: bytes

    @staticmethod
    def parse_grobro(buffer) -> Optional["GrowattModbusFunctionMultiple"]:
        unpacked = _unpack_command_header(buffer)
        if unpacked is None:
            return None

        (
            _header_id,
            _constant_7,
            _msg_len,
            _device_address,
            function,
            device_id_raw,
            start,
            end,
        ) = unpacked

        if end < start:
            return None

        values = buffer[MODBUS_COMMAND_SIZE:]
        if function == GrowattModbusFunction.PRESET_MULTIPLE_REGISTER:
            expected_value_bytes = (end - start + 1) * 2
            if len(values) != expected_value_bytes:
                return None

        device_id = device_id_raw.decode("ascii", errors="ignore").strip("\x00")
        return GrowattModbusFunctionMultiple(
            device_id=device_id,
            function=function,
            start=start,
            end=end,
            values=values,
        )

    def build_grobro(self) -> bytes:
        header = struct.pack(
            MODBUS_COMMAND_STRUCT,
            1,
            7,
            36 + len(self.values),
            1,
            self.function,
            self.device_id.encode("ascii").ljust(30, b"\x00"),
            self.start,
            self.end,
        )
        return header + self.values


class GrowattModbusFunctionSingle(BaseModel):
    """
    Represents a message that can be sent to the inverter
    to read or write a single register.

    Structure:
        - H - 2 byte header id
        - H - 2 byte constant 7
        - H - 2 byte message length
        - B - 1 byte modbus device address (normally 1 in MQTT)
        - B - 1 byte function
        - 30s - 30 byte zero-padded device id
        - H - 2 byte register
        - H - 2 byte register again for READ_SINGLE_REGISTER, or value for write
    """

    device_id: str
    function: GrowattModbusFunction
    register_no: int = Field(alias="register")
    value: int

    @staticmethod
    def parse_grobro(buffer) -> Optional["GrowattModbusFunctionSingle"]:
        unpacked = _unpack_command_header(buffer)
        if unpacked is None:
            return None

        (
            _header_id,
            _constant_7,
            _msg_len,
            _device_address,
            function,
            device_id_raw,
            register,
            value,
        ) = unpacked

        # A single-register command must not have unexplained trailing data.
        if len(buffer) != MODBUS_COMMAND_SIZE:
            return None

        device_id = device_id_raw.decode("ascii", errors="ignore").strip("\x00")
        return GrowattModbusFunctionSingle(
            device_id=device_id,
            function=function,
            register_no=register,
            value=value,
        )

    def build_grobro(self) -> bytes:
        return struct.pack(
            MODBUS_COMMAND_STRUCT,
            1,
            7,
            36,
            1,
            self.function,
            self.device_id.encode("ascii").ljust(30, b"\x00"),
            self.register_no,
            self.value,
        )

    model_config = ConfigDict(populate_by_name=True)
