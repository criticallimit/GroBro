"""Home Assistant device-timeout and shutdown hook installation."""

from __future__ import annotations

import logging
import time
from threading import Lock

from grobro.ha import client as ha_client_module
from grobro.ha.timers import cancel_runtime_timers, daemon_timer

LOG = logging.getLogger(__name__)


def install_timer_runtime() -> None:
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
                    remaining = ha_client_module.DEVICE_TIMEOUT - (time.monotonic() - last_seen)
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
                timer = daemon_timer(ha_client_module.DEVICE_TIMEOUT, check_timeout, args=(device_id,))
                self._device_timers[device_id] = timer
                timer.start()

        client_cls._Client__reset_device_timer = reset_device_timer_clean

    original_stop = client_cls.stop

    def stop_clean(self):
        cancel_runtime_timers(self)
        return original_stop(self)

    client_cls.stop = stop_clean
