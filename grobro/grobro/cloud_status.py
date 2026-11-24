"""Tiny, thread-safe Growatt Cloud link/traffic indicator for the Ingress UI.

No packet contents, counters or periodic device queries are stored.
"""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_links: dict[str, bool] = {}
_last_tx = 0.0
_last_rx = 0.0


def connecting(device_id: str) -> None:
    with _lock:
        _links[device_id] = False


def connected(device_id: str) -> None:
    with _lock:
        _links[device_id] = True


def disconnected(device_id: str) -> None:
    with _lock:
        _links[device_id] = False


def sent() -> None:
    global _last_tx
    with _lock:
        _last_tx = time.monotonic()


def received() -> None:
    global _last_rx
    with _lock:
        _last_rx = time.monotonic()


def clear() -> None:
    global _last_tx, _last_rx
    with _lock:
        _links.clear()
        _last_tx = 0.0
        _last_rx = 0.0


def snapshot(*, enabled: bool) -> dict:
    with _lock:
        total = len(_links)
        online = sum(1 for value in _links.values() if value)
        now = time.monotonic()
        return {
            "enabled": enabled,
            "status": (
                "disabled" if not enabled else
                "connected" if total and online == total else
                "partial" if online else
                "disconnected"
            ),
            # Lighting up means successful local MQTT enqueue, not Growatt
            # application-level acknowledgement.
            "tx": bool(enabled and online and _last_tx and now - _last_tx < 2.5),
            "rx": bool(enabled and online and _last_rx and now - _last_rx < 2.5),
        }
