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
        self._retry_after: dict[str, float] = {}

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
            now = time.monotonic()
            if now - created > MAX_CLOUD_MESSAGE_AGE_SECONDS:
                continue
            device_id = args[0]
            if now < self._retry_after.get(device_id, 0):
                continue
            try:
                # The source timestamp must be rechecked *after* a possibly
                # slow synchronous DNS/TLS connection, immediately before
                # forwarding the device packet to Cloud MQTT.
                self._sender(*args, received_at=created)
                self._retry_after.pop(device_id, None)
            except Exception as exc:
                # A disconnected Cloud endpoint must not cause one connection
                # attempt for every queued device packet.
                self._retry_after[device_id] = time.monotonic() + 10.0
                LOG.error("Could not forward device data to Growatt Cloud (%s)", exc)

    def stop(self) -> None:
        """Discard unforwarded packets; never join a potentially blocked DNS/TLS call."""
        with self._condition:
            self._stopped = True
            self._messages.clear()
            self._retry_after.clear()
            self._condition.notify_all()
