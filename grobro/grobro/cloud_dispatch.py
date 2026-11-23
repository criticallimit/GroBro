"""Bounded non-blocking handoff from device MQTT to optional Growatt Cloud.

The source Paho receive callback never waits for Cloud DNS/TLS. One daemon worker
preserves arrival order; no unbounded backlog or post-reconnect replay is kept.
This is exclusively used when Cloud forwarding is explicitly enabled.
"""

from __future__ import annotations

from collections import deque
import logging
import threading
import time
from typing import Callable

LOG = logging.getLogger(__name__)

MAX_PENDING_CLOUD_MESSAGES = 64
MAX_CLOUD_MESSAGE_AGE_SECONDS = 5.0


class CloudForwardQueue:
    def __init__(self, sender: Callable[[str, str, bytes, int, bool], None]):
        self._sender = sender
        self._condition = threading.Condition()
        self._messages: deque[tuple[float, tuple[str, str, bytes, int, bool]]] = deque()
        self._stopped = False
        self._thread: threading.Thread | None = None
        self._overflow_logged = False

    def submit(self, device_id: str, topic: str, payload: bytes, qos: int, retain: bool) -> bool:
        """Never block a source MQTT callback on networking or an occupied queue."""
        with self._condition:
            if self._stopped:
                return False
            if len(self._messages) >= MAX_PENDING_CLOUD_MESSAGES:
                if not self._overflow_logged:
                    LOG.warning("Growatt Cloud is slow; dropping new forwards while bounded queue is full")
                self._overflow_logged = True
                return False
            self._messages.append(
                (time.monotonic(), (device_id, topic, bytes(payload), qos, retain))
            )
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._drain,
                    name="grobro-cloud-forward",
                    daemon=True,
                )
                try:
                    self._thread.start()
                except (RuntimeError, OSError):
                    self._thread = None
                    self._messages.clear()
                    LOG.exception("Could not start Growatt Cloud forwarding worker")
                    return False
            self._condition.notify()
            return True

    def _drain(self) -> None:
        while True:
            with self._condition:
                while not self._messages and not self._stopped:
                    self._condition.wait()
                if self._stopped:
                    return
                created, args = self._messages.popleft()
                if len(self._messages) < MAX_PENDING_CLOUD_MESSAGES:
                    self._overflow_logged = False
            if time.monotonic() - created > MAX_CLOUD_MESSAGE_AGE_SECONDS:
                continue
            try:
                self._sender(*args)
            except Exception as exc:
                LOG.error("Could not forward device data to Growatt Cloud (%s)", exc)

    def stop(self) -> None:
        """Discard unforwarded packets; never join a potentially blocked DNS/TLS call."""
        with self._condition:
            self._stopped = True
            self._messages.clear()
            self._condition.notify_all()
