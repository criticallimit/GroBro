import struct
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from grobro.model.modbus_message import GrowattModbusFunction, MODBUS_FUNCTION_VALUES

_MODBUS_COMMAND = struct.Struct(">HHHBB30sHH")
MODBUS_COMMAND_SIZE = _MODBUS_COMMAND.size
TRAILER_SIZE = 2


def _unpack_command_header(buffer: bytes):
    """Return ``(header_tuple, core_length)`` or None for malformed data."""
    buffer_len = len(buffer)
    if buffer_len < MODBUS_COMMAND_SIZE:
        return None
    try:
        values = _MODBUS_COMMAND.unpack_from(buffer, 0)
    except struct.error:
        return None

    header_id, constant_7, msg_len, device_address, function, *_ = values
    if header_id != 1 or constant_7 != 7 or device_address != 1:
        return None
    if function not in MODBUS_FUNCTION_VALUES:
        return None

    # msg_len describes the packet through the final command/value byte while
    # real Growatt MQTT fixtures commonly append a separate two-byte trailer.
    core_length = msg_len + 6
    if core_length < MODBUS_COMMAND_SIZE:
        return None
    if buffer_len not in (core_length, core_length + TRAILER_SIZE):
        return None

    return values, core_length


class GrowattModbusFunctionMultiple(BaseModel):
    """Represents a message that reads or writes multiple registers."""

    device_id: str
    function: GrowattModbusFunction
    start: int
    end: int
    values: bytes

    @staticmethod
    def parse_grobro(buffer) -> Optional["GrowattModbusFunctionMultiple"]:
        parsed_header = _unpack_command_header(buffer)
        if parsed_header is None:
            return None
        unpacked, core_length = parsed_header

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

        values = buffer[MODBUS_COMMAND_SIZE:core_length]
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
        header = _MODBUS_COMMAND.pack(
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
    """Represents a message that reads or writes one register."""

    device_id: str
    function: GrowattModbusFunction
    register_no: int = Field(alias="register")
    value: int

    @staticmethod
    def parse_grobro(buffer) -> Optional["GrowattModbusFunctionSingle"]:
        parsed_header = _unpack_command_header(buffer)
        if parsed_header is None:
            return None
        unpacked, core_length = parsed_header

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

        # The command itself is exactly the common 42-byte structure; an
        # optional two-byte Growatt trailer is outside ``core_length``.
        if core_length != MODBUS_COMMAND_SIZE:
            return None

        device_id = device_id_raw.decode("ascii", errors="ignore").strip("\x00")
        return GrowattModbusFunctionSingle(
            device_id=device_id,
            function=function,
            register_no=register,
            value=value,
        )

    def build_grobro(self) -> bytes:
        return _MODBUS_COMMAND.pack(
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
