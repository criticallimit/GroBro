"""Process signal handling for the GroBro bridge."""

import logging
import signal
from threading import Event

LOG = logging.getLogger(__name__)


class SignalHandler:
    """Catch SIGINT/SIGTERM and expose a blocking shutdown wait."""

    def __init__(self):
        self._stop_event = Event()
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, _, __):
        LOG.info("Signal received, shutting down...")
        self._stop_event.set()

    @property
    def caught(self) -> bool:
        """Return whether the bridge should keep running."""
        return not self._stop_event.is_set()

    def wait(self) -> None:
        """Block until a shutdown signal is received."""
        self._stop_event.wait()
