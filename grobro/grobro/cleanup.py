"""Backward-compatible bootstrap for Better GroBro runtime hooks.

Fork-specific runtime behavior is implemented in focused hook modules. This file
keeps the historical ``install_grobro_cleanup_hook`` entry point so runtime
bootstrap code and external imports do not need to change at once.
"""

from __future__ import annotations

import logging

from grobro.grobro.noah_heater import heater_state_from_packet
from grobro.grobro.noah_heater_hook import install_noah_heater_hook
from grobro.grobro.raw_dump_hook import (
    dump_message_binary_compat,
    install_raw_dump_hook,
)

LOG = logging.getLogger(__name__)
_INSTALLED = False

# Compatibility aliases for existing tests/extensions.
_noah_heater_state_from_packet = heater_state_from_packet
_dump_message_binary_safe = dump_message_binary_compat


def install_grobro_cleanup_hook() -> None:
    """Install Better GroBro's remaining core-client compatibility hooks."""
    global _INSTALLED
    if _INSTALLED:
        return

    install_raw_dump_hook()
    install_noah_heater_hook()

    _INSTALLED = True
    LOG.info("Installed GroBro fork runtime compatibility hooks")
