from typing import Optional, Union
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field
import importlib.resources as resources
import json
import struct


class GrowattRegisterDataTypes(str, Enum):
    ENUM = "ENUM"
    STRING = "STRING"
    FLOAT = "FLOAT"
    INT = "INT"
    SIGNED_FLOAT = "SIGNED_FLOAT"
    SIGNED_INT = "SIGNED_INT"
    TIME_HHMM = "TIME_HHMM"


class GrowattRegisterEnumTypes(str, Enum):
    INT_MAP = "INT_MAP"
    BITFIELD = "BITFIELD"


_UNSIGNED_UNPACK_TYPES = {1: "!B", 2: "!H", 4: "!I"}
_SIGNED_DATA_TYPES = frozenset(
    (GrowattRegisterDataTypes.SIGNED_INT, GrowattRegisterDataTypes.SIGNED_FLOAT)
)
_FLOAT_DATA_TYPES = frozenset(
    (GrowattRegisterDataTypes.FLOAT, GrowattRegisterDataTypes.SIGNED_FLOAT)
)
_INT_DATA_TYPES = frozenset(
    (GrowattRegisterDataTypes.INT, GrowattRegisterDataTypes.SIGNED_INT)
)


class GrowattRegisterFloatOptions(BaseModel):
    delta: float = 1
    multiplier: float = 1


class GrowattRegisterEnumOptions(BaseModel):
    enum_type: GrowattRegisterEnumTypes
    values: dict[int, str]


class GrowattRegisterDataType(BaseModel):
    data_type: GrowattRegisterDataTypes
    float_options: Optional[GrowattRegisterFloatOptions] = None
    enum_options: Optional[GrowattRegisterEnumOptions] = None
    mult: Optional[float] = None

    def parse(self, data_raw: bytes | None):
        if not data_raw or not isinstance(data_raw, (bytes, bytearray, memoryview)):
            return None

        raw = bytes(data_raw)
        if self.data_type == GrowattRegisterDataTypes.STRING:
            return raw.decode("ascii", errors="ignore").strip("\x00")

        unpack_type = _UNSIGNED_UNPACK_TYPES.get(len(raw))
        if unpack_type is None:
            return None

        if self.data_type in _SIGNED_DATA_TYPES:
            unpack_type = unpack_type.lower()

        try:
            value = struct.unpack_from(unpack_type, raw, 0)[0]
        except struct.error:
            return None

        if self.data_type in _FLOAT_DATA_TYPES:
            if self.mult is not None:
                value *= self.mult
            elif self.float_options:
                value *= self.float_options.multiplier
                value += self.float_options.delta
            return round(value, 3)

        if self.data_type == GrowattRegisterDataTypes.TIME_HHMM:
            hour = (value >> 8) & 0xFF
            minute = value & 0xFF
            if hour > 23 or minute > 59:
                return None
            return f"{hour:02d}:{minute:02d}"

        if self.data_type in _INT_DATA_TYPES:
            return value

        if self.data_type == GrowattRegisterDataTypes.ENUM:
            opts = self.enum_options
            if not opts:
                return None
            if opts.enum_type == GrowattRegisterEnumTypes.BITFIELD:
                return None
            if opts.enum_type == GrowattRegisterEnumTypes.INT_MAP:
                return opts.values.get(int(value), "unknown")
        return None


class GrowattRegisterPosition(BaseModel):
    register_no: int
    offset: int = 0
    size: int = 2


class GrowattInputRegister(BaseModel):
    position: GrowattRegisterPosition
    data: GrowattRegisterDataType


class HomeAssistantHoldingRegister(BaseModel):
    name: str
    publish: bool
    type: str
    min: Optional[int] = None
    max: Optional[int] = None
    step: Optional[int] = None
    state_class: Optional[str] = None
    device_class: Optional[str] = None
    unit_of_measurement: Optional[str] = None
    icon: Optional[str] = None
    options: Optional[dict[str, str]] = None

    model_config = ConfigDict(extra="forbid")


class HomeassistantInputRegister(BaseModel):
    name: str
    publish: bool
    state_class: Optional[str] = None
    device_class: Optional[str] = None
    unit_of_measurement: Optional[str] = None
    icon: Optional[str] = None


class HomeAssistantHoldingRegisterValue(BaseModel):
    name: str
    value: Union[str, float, int]
    register_def: HomeAssistantHoldingRegister = Field(alias="register")

    model_config = ConfigDict(populate_by_name=True)


class HomeAssistantHoldingRegisterInput(BaseModel):
    device_id: str
    payload: list[HomeAssistantHoldingRegisterValue] = Field(default_factory=list)


class HomeAssistantInputRegister(BaseModel):
    device_id: str
    payload: dict[str, Union[str, float, int]] = Field(default_factory=dict)


class GroBroInputRegister(BaseModel):
    growatt: GrowattInputRegister
    homeassistant: HomeassistantInputRegister


class GroBroHoldingRegister(BaseModel):
    growatt: Optional[GrowattInputRegister] = None
    homeassistant: HomeAssistantHoldingRegister


class GroBroConfigRegister(BaseModel):
    register_no: int
    data: GrowattRegisterDataType


class HomeAssistantConfigRegister(BaseModel):
    publish: bool
    name: str
    type: str
    min: Optional[int] = None
    max: Optional[int] = None
    step: Optional[int] = None
    state_class: Optional[str] = None
    device_class: Optional[str] = None
    unit_of_measurement: Optional[str] = None
    icon: Optional[str] = None
    options: Optional[dict[str, str]] = None


class GroBroConfigRegisterDef(BaseModel):
    growatt: GroBroConfigRegister
    homeassistant: HomeAssistantConfigRegister


class GroBroRegisters(BaseModel):
    input_registers: dict[str, GroBroInputRegister]
    holding_registers: dict[str, GroBroHoldingRegister]
    config_registers: dict[str, GroBroConfigRegisterDef] = Field(default_factory=dict)


with resources.files(__package__).joinpath("growatt_neo_registers.json").open("rb") as f:
    KNOWN_NEO_REGISTERS = GroBroRegisters.model_validate(json.load(f))
with resources.files(__package__).joinpath("growatt_noah_registers.json").open("rb") as f:
    KNOWN_NOAH_REGISTERS = GroBroRegisters.model_validate(json.load(f))
with resources.files(__package__).joinpath("growatt_nexa_registers.json").open("rb") as f:
    KNOWN_NEXA_REGISTERS = GroBroRegisters.model_validate(json.load(f))

# Keep only the NOAH field that remains intentionally published from the shared
# NEXA telemetry definitions. The three temperature fields are deliberately not
# exposed for NOAH anymore.
if "batterySoh" not in KNOWN_NOAH_REGISTERS.input_registers:
    KNOWN_NOAH_REGISTERS.input_registers["batterySoh"] = (
        KNOWN_NEXA_REGISTERS.input_registers["batterySoh"].model_copy(deep=True)
    )

# These NOAH entities were experimental/debug additions and are intentionally
# removed from the effective runtime map. Keeping the removal here also protects
# against them being reintroduced accidentally by the JSON map or shared fields.
KNOWN_NOAH_REGISTERS.config_registers.pop("mqtt_ip", None)
for _removed_noah_input in ("pv1Temp", "pv2Temp", "systemTemp"):
    KNOWN_NOAH_REGISTERS.input_registers.pop(_removed_noah_input, None)

with resources.files(__package__).joinpath("growatt_spf_registers.json").open("rb") as f:
    KNOWN_SPF_REGISTERS = GroBroRegisters.model_validate(json.load(f))
with resources.files(__package__).joinpath("growatt_xh2_registers.json").open("rb") as f:
    KNOWN_XH2_REGISTERS = GroBroRegisters.model_validate(json.load(f))
with resources.files(__package__).joinpath("growatt_mod_registers.json").open("rb") as f:
    KNOWN_MOD_REGISTERS = GroBroRegisters.model_validate(json.load(f))
