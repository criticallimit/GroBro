"""Home Assistant runtime timer helpers."""

from __future__ import annotations

from threading import Timer


def daemon_timer(*args, **kwargs) -> Timer:
    """Create a Timer that never keeps the add-on process alive by itself."""
    timer = Timer(*args, **kwargs)
    timer.daemon = True
    return timer


def cancel_runtime_timers(client) -> None:
    """Cancel device/config/time-sync timers and clear related runtime state."""
    for timer_map_name in ("_device_timers", "_config_read_timers"):
        timer_map = getattr(client, timer_map_name, {})
        for timer in list(timer_map.values()):
            try:
                timer.cancel()
            except Exception:  # pragma: no cover
                pass
        timer_map.clear()

    getattr(client, "_device_last_seen", {}).clear()

    time_sync_timer = getattr(client, "_time_sync_timer", None)
    if time_sync_timer is not None:
        try:
            time_sync_timer.cancel()
        except Exception:  # pragma: no cover
            pass
        client._time_sync_timer = None
