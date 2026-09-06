"""Logging setup for the GroBro bridge."""

import logging
import os

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"


def configure_logging():
    """Configure logging with the existing LOG_LEVEL fallback behavior."""
    log_level = os.getenv("LOG_LEVEL", "ERROR").upper()
    try:
        logging.basicConfig(level=log_level, format=_LOG_FORMAT)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logging.basicConfig(level=logging.ERROR, format=_LOG_FORMAT)
        print(f"Failed to setup logger {exc} USING DEFAULT LOG Level(Error)")
    return log_level, logging.getLogger("grobro.ha_bridge")
