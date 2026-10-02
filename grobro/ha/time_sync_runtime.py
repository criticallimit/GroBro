"""Automatic Growatt clock synchronization for Home Assistant runtime."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from grobro.ha.timer_runtime import daemon_timer, guard_runtime, runtime_lock
from grobro.model.device_family import get_device_type_name, supports_time_sync

LOG = logging.getLogger(__name__)
_TIME_SYNC_REGISTER = 31
_TIME_SYNC_HOURS = (0, 12)


def seconds_until_next_time_sync(now: datetime | None = None) -> float:
    current = now or datetime.now()
    candidates = []
    for hour in _TIME_SYNC_HOURS:
        candidate = current.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(days=1)
        candidates.append(candidate)
    return max(1.0, (min(candidates) - current).total_seconds())


@guard_runtime
def sync_supported_clocks(client, now: datetime | None = None) -> int:
    callback = getattr(client, "on_config_command", None)
    if not callable(callback):
        return 0

    current = now or datetime.now()
    value = current.strftime("%Y-%m-%d %H:%M:%S")
    synced = 0
    for device_id in tuple(getattr(client, "_config_cache", {})):
        if not supports_time_sync(device_id):
            continue
        try:
            callback(device_id, _TIME_SYNC_REGISTER, value)
            synced += 1
        except Exception as exc:
            LOG.warning(
                "%s %s: automatic clock synchronization failed (%s)",
                get_device_type_name(device_id),
                device_id,
                exc,
            )
    if synced:
        LOG.info("Growatt device clocks synchronized (%s device(s))", synced)
    return synced


@guard_runtime
def schedule_next_time_sync(client) -> None:
    previous = getattr(client, "_time_sync_timer", None)
    if previous is not None:
        try:
            previous.cancel()
        except Exception:  # pragma: no cover
            pass

    def run_and_reschedule():
        with runtime_lock(client):
            if getattr(client, "_stopped", False):
                return
            client._time_sync_timer = None
            sync_supported_clocks(client)
            schedule_next_time_sync(client)

    timer = daemon_timer(seconds_until_next_time_sync(), run_and_reschedule)
    client._time_sync_timer = timer
    timer.start()
