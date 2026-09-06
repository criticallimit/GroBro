"""Home Assistant battery-count and family helper installation."""

from __future__ import annotations

from functools import lru_cache

from grobro.ha import client as ha_client_module
from grobro.model.device_family import get_device_type_name, get_known_registers

_BASE_GET_BAT_NUMBER = ha_client_module._get_bat_number


@lru_cache(maxsize=256)
def get_bat_number_cached(name: str):
    return _BASE_GET_BAT_NUMBER(name)


def detect_bat_count(payload: dict) -> int:
    bat_cnt = payload.get("bat_cnt")
    if isinstance(bat_cnt, int) and 1 <= bat_cnt <= 4:
        return bat_cnt
    count = 1
    for bat_num in range(2, 5):
        value = payload.get(f"bat{bat_num}_ser_part_1")
        if value is not None and str(value).strip("\x00 "):
            count = bat_num
    return count


def resolve_max_bat(device_id: str, payload: dict | None = None) -> int:
    if isinstance(ha_client_module.MAX_BAT, int):
        return max(1, min(4, ha_client_module.MAX_BAT))
    if payload is not None:
        count = detect_bat_count(payload)
        ha_client_module._MAX_BAT_CACHE[device_id] = count
        return count
    return ha_client_module._MAX_BAT_CACHE.get(device_id, 1)


def install_battery_runtime_helpers() -> None:
    ha_client_module.get_known_registers = get_known_registers
    ha_client_module.get_device_type_name = get_device_type_name
    ha_client_module._get_bat_number = get_bat_number_cached
    ha_client_module._detect_bat_count = detect_bat_count
    ha_client_module._resolve_max_bat = resolve_max_bat
