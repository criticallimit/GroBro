"""In-process inventory of Growatt devices seen by Better GroBro."""

from __future__ import annotations

import threading
from grobro.model.device_family import get_device_family

_LOCK = threading.Lock()
_DEVICES: dict[str, dict[str, object]] = {}


def observe_device(device_id: str) -> None:
    """Record one device that produced live telemetry."""
    device_id = str(device_id).strip()
    if not device_id:
        return

    with _LOCK:
        if device_id in _DEVICES:
            return

        family = get_device_family(device_id)
        _DEVICES[device_id] = {
            "device_id": device_id,
            "family": family.key if family else "unknown",
            "display_name": family.display_name if family else "UNKNOWN",
        }


def observe_wifi_signal(device_id: str, value) -> None:
    """Store the latest Wi-Fi signal value from device configuration."""
    device_id = str(device_id).strip()
    if not device_id or value is None:
        return
    try:
        signal = int(str(value).strip())
    except (TypeError, ValueError):
        return
    # Register 76 is defined as dBm. Zero/positive values are placeholders or
    # invalid readbacks, not usable Wi-Fi signal measurements.
    if signal >= 0 or signal < -120:
        return

    with _LOCK:
        item = _DEVICES.get(device_id)
        if item is None:
            family = get_device_family(device_id)
            item = _DEVICES[device_id] = {
                "device_id": device_id,
                "family": family.key if family else "unknown",
                "display_name": family.display_name if family else "UNKNOWN",
            }
        item["wifi_signal_strength"] = signal
        item["wifi_signal"] = signal


def observe_telemetry(device_id: str, payload: dict, max_bat: int = 1) -> None:
    """Store the small live snapshot used by the Ingress overview."""
    device_id = str(device_id).strip()
    if not device_id:
        return

    batteries = []
    for slot in range(1, max(1, min(4, int(max_bat))) + 1):
        soc = payload.get(f"bat_{slot}_soc_pct")
        temp = payload.get(f"bat{slot}_temp")
        battery = {"slot": slot}
        if soc is not None:
            battery["soc"] = soc
        if temp is not None:
            battery["temperature"] = temp
        batteries.append(battery)

    with _LOCK:
        item = _DEVICES.get(device_id)
        if item is None:
            family = get_device_family(device_id)
            item = _DEVICES[device_id] = {
                "device_id": device_id,
                "family": family.key if family else "unknown",
                "display_name": family.display_name if family else "UNKNOWN",
            }
        item["batteries"] = batteries
        for key in (
            "bat_sysstate",
            "charging_discharging",
            "out_power",
            "pv_tot_power",
            "tot_bat_soc_pct",
            "wifi_signal_strength",
        ):
            value = payload.get(key)
            if value is not None:
                item[key] = value


def get_device_inventory() -> list[dict[str, object]]:
    """Return a stable snapshot sorted by family/name and device id."""
    with _LOCK:
        snapshot = []
        for item in _DEVICES.values():
            copy = dict(item)
            if "batteries" in copy:
                copy["batteries"] = [dict(battery) for battery in copy["batteries"]]
            snapshot.append(copy)
    return sorted(
        snapshot,
        key=lambda item: (item["display_name"], item["device_id"]),
    )


def clear_device_inventory() -> None:
    """Test helper."""
    with _LOCK:
        _DEVICES.clear()
