"""In-process inventory of Growatt devices seen by Better GroBro."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from grobro.model.device_family import get_device_family

_LOCK = threading.Lock()
_DEVICES: dict[str, dict[str, str]] = {}


def observe_device(device_id: str) -> None:
    """Record one device that produced live telemetry."""
    device_id = str(device_id).strip()
    if not device_id:
        return

    family = get_device_family(device_id)
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "device_id": device_id,
        "family": family.key if family else "unknown",
        "display_name": family.display_name if family else "UNKNOWN",
        "last_seen": now,
    }
    with _LOCK:
        _DEVICES[device_id] = entry


def get_device_inventory() -> list[dict[str, str]]:
    """Return a stable snapshot sorted by family/name and device id."""
    with _LOCK:
        snapshot = [dict(item) for item in _DEVICES.values()]
    return sorted(
        snapshot,
        key=lambda item: (item["display_name"], item["device_id"]),
    )


def clear_device_inventory() -> None:
    """Test helper."""
    with _LOCK:
        _DEVICES.clear()
