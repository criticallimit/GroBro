"""Central Growatt device-family registry.

All runtime components use this module for serial-prefix detection, register-map
selection, display names, and family capabilities. Keeping this information in
one place prevents the MQTT and Home Assistant paths from drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from grobro.model.growatt_registers import (
    GroBroRegisters,
    GrowattRegisterDataTypes,
    KNOWN_MOD_REGISTERS,
    KNOWN_NEO_REGISTERS,
    KNOWN_NEXA_REGISTERS,
    KNOWN_NOAH_REGISTERS,
    KNOWN_SPF_REGISTERS,
    KNOWN_XH2_REGISTERS,
)

_TIME_SYNC_REGISTER = 31


@dataclass(frozen=True, slots=True)
class DeviceFamily:
    key: str
    display_name: str
    prefixes: tuple[str, ...]
    registers: GroBroRegisters
    dynamic_pv_count: bool = False
    is_gateway: bool = False


DEVICE_FAMILIES: tuple[DeviceFamily, ...] = (
    DeviceFamily(
        key="noah",
        display_name="NOAH",
        prefixes=("0PVP",),
        registers=KNOWN_NOAH_REGISTERS,
    ),
    DeviceFamily(
        key="nexa",
        display_name="NEXA",
        prefixes=("0HVR",),
        registers=KNOWN_NEXA_REGISTERS,
    ),
    DeviceFamily(
        key="neo",
        display_name="NEO",
        prefixes=("QMN", "PTQ"),
        registers=KNOWN_NEO_REGISTERS,
        dynamic_pv_count=True,
    ),
    # RAQ identifies the ShineWeLink gateway. Its parsed inverter/config payload
    # currently uses the NEO register model, but writes must target the PTQ
    # inverter behind it rather than the RAQ gateway itself.
    DeviceFamily(
        key="shinewelink",
        display_name="ShineWeLink",
        prefixes=("RAQ",),
        registers=KNOWN_NEO_REGISTERS,
        is_gateway=True,
    ),
    DeviceFamily(
        key="spf",
        display_name="SPF",
        prefixes=("HAQ",),
        registers=KNOWN_SPF_REGISTERS,
    ),
    DeviceFamily(
        key="min_xh2",
        display_name="MIN-XH2",
        prefixes=("ZGQ",),
        registers=KNOWN_XH2_REGISTERS,
    ),
    DeviceFamily(
        key="mod",
        display_name="MOD",
        prefixes=("VWQ",),
        registers=KNOWN_MOD_REGISTERS,
        dynamic_pv_count=True,
    ),
)

_PREFIX_TO_FAMILY = {
    prefix: family
    for family in DEVICE_FAMILIES
    for prefix in family.prefixes
}
_PREFIX_LENGTHS = tuple(sorted({len(prefix) for prefix in _PREFIX_TO_FAMILY}, reverse=True))


@lru_cache(maxsize=128)
def get_device_family(device_id: str) -> DeviceFamily | None:
    """Resolve one stable device serial to its family with a tiny process cache."""
    text = str(device_id)
    for prefix_len in _PREFIX_LENGTHS:
        family = _PREFIX_TO_FAMILY.get(text[:prefix_len])
        if family is not None:
            return family
    return None


def get_known_registers(device_id: str) -> GroBroRegisters | None:
    family = get_device_family(device_id)
    return family.registers if family else None


def get_device_type_name(device_id: str) -> str:
    family = get_device_family(device_id)
    return family.display_name if family else "UNKNOWN"


def _register_map_supports_time_sync(registers: GroBroRegisters) -> bool:
    system_time = registers.config_registers.get("system_time")
    if system_time is None:
        return False
    return (
        system_time.growatt.register_no == _TIME_SYNC_REGISTER
        and system_time.growatt.data.data_type == GrowattRegisterDataTypes.STRING
    )


def supports_time_sync(device_id: str) -> bool:
    """Return whether this device can safely receive the shared clock write.

    Capability is derived from the active register map rather than duplicated in
    family metadata. Gateways are always excluded because writes must target the
    inverter/device behind them.
    """
    family = get_device_family(device_id)
    return bool(
        family
        and not family.is_gateway
        and _register_map_supports_time_sync(family.registers)
    )


def uses_dynamic_pv_count(device_id: str) -> bool:
    family = get_device_family(device_id)
    return bool(family and family.dynamic_pv_count)
