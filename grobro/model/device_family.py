"""Central Growatt device-family registry.

All runtime components use this module for serial-prefix detection, register-map
selection, display names, and family capabilities. Keeping this information in
one place prevents the MQTT and Home Assistant paths from drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from grobro.model.growatt_registers import (
    GroBroRegisters,
    KNOWN_MOD_REGISTERS,
    KNOWN_NEO_REGISTERS,
    KNOWN_NEXA_REGISTERS,
    KNOWN_NOAH_REGISTERS,
    KNOWN_SPF_REGISTERS,
    KNOWN_XH2_REGISTERS,
)


@dataclass(frozen=True, slots=True)
class DeviceFamily:
    key: str
    display_name: str
    prefixes: tuple[str, ...]
    registers: GroBroRegisters
    supports_time_sync: bool = False
    dynamic_pv_count: bool = False


DEVICE_FAMILIES: tuple[DeviceFamily, ...] = (
    DeviceFamily(
        key="noah",
        display_name="NOAH",
        prefixes=("0PVP",),
        registers=KNOWN_NOAH_REGISTERS,
        supports_time_sync=True,
    ),
    DeviceFamily(
        key="nexa",
        display_name="NEXA",
        prefixes=("0HVR",),
        registers=KNOWN_NEXA_REGISTERS,
        supports_time_sync=True,
    ),
    DeviceFamily(
        key="neo",
        display_name="NEO",
        prefixes=("QMN", "PTQ"),
        registers=KNOWN_NEO_REGISTERS,
        supports_time_sync=True,
        dynamic_pv_count=True,
    ),
    # RAQ identifies the ShineWeLink gateway. Its parsed inverter/config payload
    # currently uses the NEO register model, but writes such as clock sync must
    # target the PTQ inverter behind it rather than the RAQ gateway itself.
    DeviceFamily(
        key="shinewelink",
        display_name="ShineWeLink",
        prefixes=("RAQ",),
        registers=KNOWN_NEO_REGISTERS,
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


def get_device_family(device_id: str) -> DeviceFamily | None:
    text = str(device_id)
    for family in DEVICE_FAMILIES:
        if text.startswith(family.prefixes):
            return family
    return None


def get_known_registers(device_id: str) -> GroBroRegisters | None:
    family = get_device_family(device_id)
    return family.registers if family else None


def get_device_type_name(device_id: str) -> str:
    family = get_device_family(device_id)
    return family.display_name if family else "UNKNOWN"


def supports_time_sync(device_id: str) -> bool:
    family = get_device_family(device_id)
    return bool(family and family.supports_time_sync)


def uses_dynamic_pv_count(device_id: str) -> bool:
    family = get_device_family(device_id)
    return bool(family and family.dynamic_pv_count)
