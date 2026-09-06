from typing import Optional
from datetime import datetime
import struct
import logging
from pydantic.main import BaseModel
from enum import Enum
from grobro.model.growatt_registers import GrowattRegisterPosition

LOG = logging.getLogger(__name__)

HEADER_STRUCT = ">HHHBB30s"
HEADER_SIZE = struct.calcsize(HEADER_STRUCT)
MIN_BLOCK_SIZE = 6  # start + end + one 16-bit register
TRAILER_SIZE = 2  # Growatt packets commonly carry a two-byte protocol trailer/CRC


class GrowattModbusBlock(BaseModel):
    """
    Represents a block of modbus registers.
    start, end are the number of the first and last register included.
    values are the registers between start and end, each value 2 bytes.

    Each register block:
        - H - 2 byte start register
        - H - 2 byte end register (M=end-start+1)
        - M x H - M x 2 byte register values
    """

    start: int
    end: int
    values: bytes

    @staticmethod
    def parse_grobro(buffer, offset: int = 0) -> Optional["GrowattModbusBlock"]:
        try:
            if offset < 0 or len(buffer) - offset < 4:
                return None

            start, end = struct.unpack_from(">HH", buffer, offset)
            if end < start:
                LOG.warning("Invalid register block range: %s..%s", start, end)
                return None

            register_count = end - start + 1
            expected_size = 4 + register_count * 2
            if len(buffer) - offset < expected_size:
                LOG.warning(
                    "Truncated register block %s..%s: need %s bytes, got %s",
                    start,
                    end,
                    expected_size,
                    len(buffer) - offset,
                )
                return None

            values_start = offset + 4
            values_end = offset + expected_size
            return GrowattModbusBlock(
                start=start,
                end=end,
                values=buffer[values_start:values_end],
            )
        except (struct.error, ValueError) as exc:
            LOG.warning("Parsing GrowattModbusBlock: %s", exc)
            return None

    def build_grobro(self) -> bytes:
        return struct.pack(">HH", self.start, self.end) + self.values

    def size(self):
        return 4 + len(self.values)


class GrowattModbusFunction(int, Enum):
    READ_HOLDING_REGISTER = 3
    READ_INPUT_REGISTER = 4
    READ_SINGLE_REGISTER = 5
    PRESET_SINGLE_REGISTER = 6
    PRESET_MULTIPLE_REGISTER = 16
    VENDOR_100 = 100


MODBUS_FUNCTION_VALUES = frozenset(entry.value for entry in GrowattModbusFunction)


class GrowattMetadata(BaseModel):
    """
    Represents metadata within a READ_INPUT_REGISTER message.

    Structure:
    - 30s - zero padded device serial
    - 7B - timestamp in interesting format
    """

    device_sn: str
    timestamp: Optional[datetime]

    def size(self):
        return 37

    @staticmethod
    def parse_grobro(buffer, offset: int = 0) -> Optional["GrowattMetadata"]:
        if offset < 0 or len(buffer) - offset < 37:
            return None

        try:
            device_serial_raw = struct.unpack_from(">30s", buffer, offset)[0]
            device_serial = device_serial_raw.decode("ascii", errors="ignore").strip("\x00")
            year, month, day, hour, minute, second, millis = struct.unpack_from(
                ">7B", buffer, offset + 30
            )
        except struct.error:
            return None

        timestamp = None
        try:
            timestamp = datetime(
                year + 2000,
                month,
                day,
                hour,
                minute,
                second,
                microsecond=millis * 1000,
            )
        except ValueError:
            pass

        return GrowattMetadata(device_sn=device_serial, timestamp=timestamp)

    def build_grobro(self) -> bytes:
        if self.timestamp is None:
            raise ValueError("metadata timestamp is required when building a message")

        return struct.pack(
            ">30s7B",
            self.device_sn.encode("ascii").ljust(30, b"\x00"),
            self.timestamp.year - 2000,
            self.timestamp.month,
            self.timestamp.day,
            self.timestamp.hour,
            self.timestamp.minute,
            self.timestamp.second,
            int(self.timestamp.microsecond / 1000),
        )


class GrowattModbusMessage(BaseModel):
    """
    Represents a block of modbus registers sent by the growatt device.

    Header Structure:
        - H - 2 byte unknown
        - H - 2 byte constant 7
        - H - 2 byte message length (excluding register count, constant and message length)
        - B - 1 byte modbus device address (seems to be constant 1 in mqtt)
        - B - 1 byte function
        - 30s - 30 byte zero-padded device id
        - optional GrowattModbusMetadata - only present when function == READ_INPUT_REGISTER
        - N register blocks
        - optional 2-byte Growatt trailer/CRC
    """

    unknown: int
    device_id: str
    metadata: Optional[GrowattMetadata] = None
    function: GrowattModbusFunction
    register_blocks: list[GrowattModbusBlock]

    @property
    def msg_len(self):
        result = 32  # 2 byte msg_type + 30 byte device id
        if self.metadata:
            result += self.metadata.size()
        for block in self.register_blocks:
            result += block.size()
        return result

    def get_data(self, pos: GrowattRegisterPosition):
        blocks = self.register_blocks

        if len(blocks) == 1:
            block = blocks[0]
            if block.start > pos.register_no or block.end < pos.register_no:
                return None
            block_pos = (pos.register_no - block.start) * 2 + pos.offset
            end_pos = block_pos + pos.size
            if block_pos < 0 or end_pos > len(block.values):
                return None
            return block.values[block_pos:end_pos]

        for block in blocks:
            if block.start > pos.register_no or block.end < pos.register_no:
                continue
            block_pos = (pos.register_no - block.start) * 2 + pos.offset
            end_pos = block_pos + pos.size
            if block_pos < 0 or end_pos > len(block.values):
                return None
            return block.values[block_pos:end_pos]
        return None

    @staticmethod
    def parse_grobro(buffer) -> Optional["GrowattModbusMessage"]:
        try:
            if len(buffer) < HEADER_SIZE:
                return None

            unknown, constant_7, msg_len, _constant_1, function, device_id_raw = struct.unpack_from(
                HEADER_STRUCT,
                buffer,
                0,
            )

            if constant_7 != 7:
                LOG.debug("Unexpected Growatt header constant: %s", constant_7)
                return None
            if msg_len != len(buffer) - 8:
                return None

            device_id = device_id_raw.decode("ascii", errors="ignore").strip("\x00")
            if function not in MODBUS_FUNCTION_VALUES:
                LOG.debug("Unknown modbus function for %s: %s", device_id, function)
                return None

            register_blocks = []
            offset = HEADER_SIZE

            metadata = None
            if function == GrowattModbusFunction.READ_INPUT_REGISTER:
                metadata = GrowattMetadata.parse_grobro(buffer, offset)
                if metadata is None:
                    LOG.warning("Missing or truncated input-register metadata for %s", device_id)
                    return None
                offset += metadata.size()

            # A one-register block is exactly six bytes. Equality must be accepted
            # so a final single-register block is not skipped.
            while len(buffer) - offset >= MIN_BLOCK_SIZE:
                block = GrowattModbusBlock.parse_grobro(buffer, offset)
                if block is None:
                    return None
                register_blocks.append(block)
                offset += block.size()

            remaining = len(buffer) - offset
            # Real Growatt telemetry fixtures carry a two-byte trailer/CRC after
            # the last register block. Synthetic/unit-built messages may omit it.
            if remaining not in (0, TRAILER_SIZE):
                LOG.debug(
                    "Unexpected trailing bytes after Modbus blocks for %s: %s",
                    device_id,
                    remaining,
                )
                return None

            return GrowattModbusMessage(
                unknown=unknown,
                metadata=metadata,
                device_id=device_id,
                function=function,
                register_blocks=register_blocks,
            )
        except (struct.error, ValueError) as exc:
            LOG.warning("parsing GrowattModbusMessage: %s", exc)
            return None

    def build_grobro(self) -> bytes:
        result = struct.pack(
            HEADER_STRUCT,
            self.unknown,
            7,
            self.msg_len,
            1,
            self.function,
            self.device_id.encode("ascii").ljust(30, b"\x00"),
        )
        if self.metadata:
            result += self.metadata.build_grobro()
        for block in self.register_blocks:
            result += block.build_grobro()
        return result
