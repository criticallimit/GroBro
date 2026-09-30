"""In-memory log buffer for the Better GroBro Ingress log viewer."""

from __future__ import annotations

from collections import deque
from datetime import datetime
import logging
import threading

_STARTED_AT = datetime.now().astimezone().isoformat(timespec="seconds")
_LINES: deque[str] = deque(maxlen=4000)
_LOCK = threading.Lock()
_HANDLER: logging.Handler | None = None


class _IngressLogHandler(logging.Handler):
    """Capture formatted log records without touching Supervisor or disk."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:  # pragma: no cover - logging must never break runtime
            self.handleError(record)
            return
        with _LOCK:
            _LINES.append(line)


def install_runtime_log_handler(format_string: str) -> None:
    """Install one process-local handler on the root logger."""
    global _HANDLER
    if _HANDLER is not None:
        return

    handler = _IngressLogHandler()
    handler.setFormatter(logging.Formatter(format_string))
    logging.getLogger().addHandler(handler)
    _HANDLER = handler


def get_runtime_logs() -> dict:
    """Return logs captured since this Better GroBro process started."""
    with _LOCK:
        text = "\n".join(_LINES)
    if text:
        text += "\n"
    return {
        "logs": text,
        "started_at": _STARTED_AT,
        "marker_found": True,
    }
