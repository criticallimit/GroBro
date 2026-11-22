"""Nominal total battery storage capacity for supported 2.048 kWh packs.

The sensor is a nameplate capacity, not stored energy, charge throughput,
or battery health-adjusted usable energy. Do not infer counts from stale slots.
"""
from __future__ import annotations

import math

from grobro.model.device_family import get_device_family

PACK_CAPACITY_KWH = 2.048
SENSOR_KEY = "battery_total_capacity_kwh"


def nominal_battery_capacity(device_id: str, payload: dict) -> float | None:
    family = get_device_family(device_id)
    if not family or family.key not in ("noah", "nexa"):
        return None

    key = "bat_cnt" if family.key == "noah" else "batteryPackageQuantity"
    reported = payload.get(key)
    if isinstance(reported, bool) or not isinstance(reported, (int, float)):
        return None
    if not math.isfinite(reported) or not float(reported).is_integer():
        return None
    count = int(reported)
    if not 1 <= count <= 4:
        return None

    return round(count * PACK_CAPACITY_KWH, 3)
