"""Persist last valid state-like sensor readings without faking live telemetry.

Only values that are meaningful while a battery is disconnected are restored.
The data lives in the add-on's existing persistent /share mount. No command,
energy counter or live power/current measurements are ever replayed.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

LOG = logging.getLogger(__name__)
MAX_AGE_SECONDS = 12 * 60 * 60
SAVE_INTERVAL_SECONDS = 300
_SAFE_DEVICE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _file(device_id: str) -> Path | None:
    if not _SAFE_DEVICE_ID.fullmatch(device_id):
        return None
    directory = Path(os.getenv("BETTER_GROBRO_STATE_DIR", "/share/GroBro/state_cache"))
    return directory / ("state_" + device_id + ".json")


def _load(device_id: str) -> dict:
    path = _file(device_id)
    if path is None:
        return {"values": {}, "max_bat": 1}
    try:
        with path.open("r", encoding="utf-8") as stream:
            obj = json.load(stream)
        if not isinstance(obj, dict) or not isinstance(obj.get("values"), dict):
            raise ValueError("invalid cache format")
        return obj
    except FileNotFoundError:
        return {"values": {}, "max_bat": 1}
    except (OSError, ValueError, TypeError) as exc:
        LOG.warning("Ignoring invalid Better GroBro state cache for %s: %s", device_id, exc)
        return {"values": {}, "max_bat": 1}


def _store(client, device_id: str) -> dict:
    stores = getattr(client, "_persistent_sensor_cache", None)
    if stores is None:
        stores = client._persistent_sensor_cache = {}
    if device_id not in stores:
        stores[device_id] = _load(device_id)
    return stores[device_id]


def saved_max_bat(client, device_id: str) -> int:
    count = _store(client, device_id).get("max_bat", 1)
    return count if isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= 4 else 1


def _is_hold_value(name: str, register) -> bool:
    """Keep state and battery values; exclude energy counters and live telemetry."""
    ha = getattr(register, "homeassistant", None)
    if ha is None or getattr(ha, "state_class", None) in ("total", "total_increasing"):
        return False
    device_class = getattr(ha, "device_class", None)
    if device_class in ("temperature", "battery"):
        return True
    lower = name.lower()
    if lower in ("bat_soh", "tot_bat_soc_pct") or "soc" in lower or "soh" in lower:
        return True
    if lower.startswith("bat") and any(tag in lower for tag in ("volt", "cv", "ser_", "serial", "status", "sysstate")):
        return True
    if lower.startswith(("maxcvbat", "mincvbat")):
        return True
    return False


def _valid(value) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        import math
        return math.isfinite(value)
    return isinstance(value, (str, bool))


def merge_state(client, device_id: str, payload: dict, known_registers, *, detected_bat_count: int, max_bat: int, preserve_assignment_gaps: bool = False) -> dict:
    """Preserve recent stable measurements missing from an incomplete device frame.

    A disconnected battery sometimes sends zero placeholders even though its
    actual data is absent. Only treat them as missing for slots beyond the
    device's *currently detected* count, never for an online 0% battery.
    """
    from grobro.ha.register_helpers import _get_bat_number

    cache = _store(client, device_id)
    cached = cache.setdefault("values", {})
    now = time.time()
    result = dict(payload)
    changed = False

    if isinstance(max_bat, int) and max_bat > saved_max_bat(client, device_id):
        cache["max_bat"] = min(max_bat, 4)
        changed = True

    if known_registers is not None:
        for name, reg in known_registers.input_registers.items():
            if not _is_hold_value(name, reg):
                continue
            slot = _get_bat_number(name)
            if slot is not None and slot > max_bat:
                continue
            # A live serial-based reordering can intentionally leave an old
            # logical slot empty. Never resurrect a value into that slot.
            if preserve_assignment_gaps and slot is not None and name not in result:
                continue
            value = result.get(name)
            placeholder = (
                slot is not None
                and slot > detected_bat_count
                and value in (0, 0.0, "", None)
            )
            if _valid(value) and not placeholder:
                previous = cached.get(name)
                # Refresh freshness on every valid reading, but persist no more
                # often than the normal save interval to avoid SD-card wear.
                if (
                    not isinstance(previous, dict)
                    or previous.get("value") != value
                    or now - previous.get("observed_at", 0) >= SAVE_INTERVAL_SECONDS
                ):
                    changed = True
                cached[name] = {"value": value, "observed_at": now}
            else:
                previous = cached.get(name)
                if isinstance(previous, dict):
                    seen = previous.get("observed_at")
                    if isinstance(seen, (float, int)) and 0 <= now - seen <= MAX_AGE_SECONDS and _valid(previous.get("value")):
                        result[name] = previous["value"]

    if changed:
        dirty = getattr(client, "_persistent_sensor_cache_dirty", None)
        if dirty is None:
            dirty = client._persistent_sensor_cache_dirty = set()
        dirty.add(device_id)
    flush(client)
    return result


def flush(client, *, force: bool = False) -> None:
    dirty = getattr(client, "_persistent_sensor_cache_dirty", None)
    if not dirty:
        return
    saved = getattr(client, "_persistent_sensor_cache_saved_at", None)
    if saved is None:
        saved = client._persistent_sensor_cache_saved_at = {}
    now = time.monotonic()
    for device_id in tuple(dirty):
        if not force and now - saved.get(device_id, float("-inf")) < SAVE_INTERVAL_SECONDS:
            continue
        path = _file(device_id)
        if path is None:
            dirty.discard(device_id)
            continue
        tmp = path.with_suffix(".json.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tmp.open("w", encoding="utf-8") as stream:
                json.dump(_store(client, device_id), stream, separators=(",", ":"))
            os.replace(tmp, path)
        except (OSError, TypeError, ValueError) as exc:
            # Keep the dirty value for a later retry, but do not try the same
            # unwritable mount on every incoming device packet.
            saved[device_id] = now
            LOG.warning("Unable to persist Better GroBro state for %s: %s", device_id, exc)
            continue
        saved[device_id] = now
        dirty.discard(device_id)
