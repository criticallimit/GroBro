"""Bounded diagnostic I/O with lossless JSONL records and recent-history rotation."""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from contextvars import ContextVar
from functools import wraps

LOG = logging.getLogger(__name__)
MAX_FILE_BYTES = 10 * 1024 * 1024
BACKUPS = 3
_FILE_LOCK = threading.RLock()
_ACTIVE_WRITER = ContextVar("grobro_diagnostic_writer", default=None)


def diagnostic_scope(callback):
    """Route diagnostic writes from MQTT callbacks to their instance worker."""
    @wraps(callback)
    def scoped(client, *args, **kwargs):
        token = _ACTIVE_WRITER.set(getattr(client, "_diagnostic_writer", None))
        try:
            return callback(client, *args, **kwargs)
        finally:
            _ACTIVE_WRITER.reset(token)
    return scoped


def _write_lines(path: str, text: str) -> None:
    with _FILE_LOCK:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        try:
            existing = os.path.getsize(path)
        except FileNotFoundError:
            existing = 0
        handle = None
        try:
            for line in text.splitlines(keepends=True):
                size = len(line.encode("utf-8"))
                if size > MAX_FILE_BYTES:
                    LOG.warning("Diagnostic record exceeds file limit; discarded")
                    continue
                if existing and existing + size > MAX_FILE_BYTES:
                    if handle is not None:
                        handle.close()
                        handle = None
                    oldest = f"{path}.{BACKUPS}"
                    if os.path.exists(oldest):
                        os.remove(oldest)
                    for index in range(BACKUPS - 1, 0, -1):
                        source = f"{path}.{index}"
                        if os.path.exists(source):
                            os.replace(source, f"{path}.{index + 1}")
                    os.replace(path, f"{path}.1")
                    existing = 0
                if handle is None:
                    handle = open(path, "a", encoding="utf-8", newline="\n")
                handle.write(line)
                existing += size
        finally:
            if handle is not None:
                handle.close()


def append_lines(path: str, text: str) -> None:
    writer = _ACTIVE_WRITER.get()
    if writer is not None:
        writer.submit(os.path.abspath(path), text)
    else:
        _write_lines(path, text)


class DiagnosticWriter:
    """One lazy worker; bounded queue and bounded shutdown even on slow storage."""
    def __init__(self, max_jobs: int = 256, max_bytes: int = 4 * 1024 * 1024):
        self._condition = threading.Condition()
        self._queue = deque()
        self._bytes = 0
        self._active = False
        self._closed = False
        self._thread = None
        self._warned = False
        self._write_failed = False
        self._max_jobs, self._max_bytes = max_jobs, max_bytes

    def submit(self, path: str, text: str) -> bool:
        size = len(text.encode("utf-8"))
        with self._condition:
            if self._closed:
                return False
            if len(self._queue) >= self._max_jobs or self._bytes + size > self._max_bytes:
                if not self._warned:
                    LOG.warning("Diagnostic queue is full; capture discarded")
                    self._warned = True
                return False
            self._queue.append((path, text, size))
            self._bytes += size
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="grobro-diagnostics", daemon=True)
                try:
                    self._thread.start()
                except (RuntimeError, OSError):
                    self._thread = None
                    self._queue.pop()
                    self._bytes -= size
                    LOG.exception("Could not start diagnostic writer; capture discarded")
                    return False
            self._condition.notify_all()
            return True

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._queue or self._closed)
                if not self._queue:
                    return
                path, text, size = self._queue.popleft()
                self._active = True
            try:
                _write_lines(path, text)
                self._write_failed = False
            except Exception:
                if not self._write_failed:
                    LOG.exception("Could not write diagnostic capture")
                self._write_failed = True
            finally:
                with self._condition:
                    self._bytes -= size
                    self._active = False
                    if not self._queue:
                        self._warned = False
                    self._condition.notify_all()

    def flush(self, timeout: float = 2) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: not self._queue and not self._active, timeout)

    def stop(self, timeout: float = 2) -> bool:
        started = time.monotonic()
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(max(0, timeout - (time.monotonic() - started)))
            if self._thread.is_alive():
                LOG.warning("Diagnostic storage is delayed; shutdown drain timed out")
                return False
        return True
