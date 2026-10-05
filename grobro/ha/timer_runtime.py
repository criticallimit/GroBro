"""Home Assistant timer helpers, device timeout and shutdown handling."""

from __future__ import annotations

from threading import Timer
from contextlib import nullcontext
from functools import wraps

from grobro.ha import client as ha_client_module


def runtime_lock(client):
    """Share the stop/schedule lock; support older lightweight API callers."""
    return getattr(client, "_runtime_lock", None) or nullcontext()


def guard_runtime(callback):
    """Serialize runtime callbacks with shutdown, including timer callbacks."""
    @wraps(callback)
    def guarded(client, *args, **kwargs):
        with runtime_lock(client):
            if getattr(client, "_stopped", False):
                return None
            return callback(client, *args, **kwargs)
    return guarded



def daemon_timer(*args, **kwargs) -> Timer:
    """Create a Timer that never keeps the add-on process alive by itself."""
    timer = Timer(*args, **kwargs)
    timer.daemon = True
    return timer


def cancel_runtime_timers(client) -> None:
    """Cancel device/config/time-sync timers and clear related runtime state."""
    for timer_map_name in ("_device_timers", "_config_read_timers", "_read_all_start_timers"):
        timer_map = getattr(client, timer_map_name, {})
        for timer in list(timer_map.values()):
            try:
                timer.cancel()
            except Exception:  # pragma: no cover
                pass
        timer_map.clear()

    getattr(client, "_device_last_seen", {}).clear()
    for state in ("_config_read_queues", "_config_read_inflight", "_read_all_active", "_config_refresh_started"):
        getattr(client, state, {}).clear()

    time_sync_timer = getattr(client, "_time_sync_timer", None)
    if time_sync_timer is not None:
        try:
            time_sync_timer.cancel()
        except Exception:  # pragma: no cover
            pass
        client._time_sync_timer = None

    neo_probe_timer = getattr(client, "_neo_startup_probe_timer", None)
    if neo_probe_timer is not None:
        try:
            neo_probe_timer.cancel()
        except Exception:  # pragma: no cover
            pass
        client._neo_startup_probe_timer = None


def effective_device_timeout(client, device_id: str) -> float:
    """Return a timeout long enough for the device's configured report interval.

    DEVICE_TIMEOUT remains the minimum. Devices such as NEO can report only every
    few minutes, so use the persisted data_interval plus 20% jitter allowance
    (at least 30 seconds) before marking the device unavailable.
    """
    timeout = float(ha_client_module.DEVICE_TIMEOUT)
    config = getattr(client, "_config_cache", {}).get(device_id)
    raw_interval = getattr(config, "data_interval", None) if config is not None else None
    try:
        interval_minutes = float(raw_interval)
    except (TypeError, ValueError):
        return timeout

    if not 0 < interval_minutes <= 60:
        return timeout

    interval_seconds = interval_minutes * 60.0
    grace = max(30.0, interval_seconds * 0.20)
    return max(timeout, interval_seconds + grace)
