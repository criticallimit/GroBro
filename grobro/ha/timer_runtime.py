"""Home Assistant timer helpers, device timeout and shutdown handling."""

from __future__ import annotations

import logging
import time
from threading import Lock, Timer

from grobro.ha import client as ha_client_module

LOG = logging.getLogger(__name__)


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


def install_timer_runtime() -> None:
    """Install daemon timers, device timeout handling and shutdown cleanup."""
    ha_client_module.Timer = daemon_timer
    client_cls = ha_client_module.Client

    if ha_client_module.DEVICE_TIMEOUT > 0:

        def reset_device_timer_clean(self, device_id: str):
            now = time.monotonic()
            lock = getattr(self, "_device_timer_lock", None)
            if lock is None:
                lock = Lock()
                self._device_timer_lock = lock

            def check_timeout(d_id: str):
                with lock:
                    last_seen = self._device_last_seen.get(d_id)
                    if last_seen is None:
                        self._device_timers.pop(d_id, None)
                        return
                    timeout = effective_device_timeout(self, d_id)
                    remaining = timeout - (time.monotonic() - last_seen)
                    if remaining > 0:
                        timer = daemon_timer(remaining, check_timeout, args=(d_id,))
                        self._device_timers[d_id] = timer
                        timer.start()
                        return
                    self._device_timers.pop(d_id, None)
                    self._device_last_seen.pop(d_id, None)

                LOG.warning("Device %s timed out. Mark it as unavailable.", d_id)
                self._Client__publish_availability(d_id, False)

            with lock:
                self._device_last_seen[device_id] = now
                timer = self._device_timers.get(device_id)
                if timer is not None and timer.is_alive():
                    return
                timer = daemon_timer(
                    effective_device_timeout(self, device_id),
                    check_timeout,
                    args=(device_id,),
                )
                self._device_timers[device_id] = timer
                timer.start()

        client_cls._Client__reset_device_timer = reset_device_timer_clean

    original_stop = client_cls.stop

    def stop_clean(self):
        cancel_runtime_timers(self)
        return original_stop(self)

    client_cls.stop = stop_clean
