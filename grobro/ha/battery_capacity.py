"""Estimate currently stored battery energy from *live* Growatt SoC and pack count.

This represents a state-of-charge estimate in kWh, not nominal capacity and
not energy charged or discharged over time. Never use stale battery slots.
"""
from __future__ import annotations

import math

from grobro.model.device_family import get_device_family

PACK_CAPACITY_KWH = 2.048
SENSOR_KEY = "battery_stored_energy_kwh"


def _valid_number(value, *, lower: float, upper: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    if not math.isfinite(value) or not lower <= value <= upper:
        return None
    return float(value)


def current_battery_energy(device_id: str, payload: dict) -> float | None:
    """Compute a kWh estimate only when count and aggregate SoC are current.

    The overall SoC comes from the device and includes the entire reported
    battery stack. A missing / implausible SoC is unknown, never 0 kWh.
    """
    family = get_device_family(device_id)
    if family is None or family.key not in ("noah", "nexa"):
        return None

    if family.key == "noah":
        count_key, soc_key = "bat_cnt", "tot_bat_soc_pct"
    else:
        count_key, soc_key = "batteryPackageQuantity", "totalBatteryPackSoc"

    count = _valid_number(payload.get(count_key), lower=1, upper=4)
    soc = _valid_number(payload.get(soc_key), lower=0, upper=100)
    if count is None or not count.is_integer() or soc is None:
        return None

    return round(int(count) * PACK_CAPACITY_KWH * soc / 100, 3)
