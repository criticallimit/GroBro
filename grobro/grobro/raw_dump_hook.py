"""Compatibility hook routing legacy raw dumps to the centralized JSONL dumper."""

from __future__ import annotations

import logging

from grobro.grobro import client as grobro_client_module
from grobro.grobro.raw_dump import dump_message_jsonl

LOG = logging.getLogger(__name__)
_INSTALLED = False


def dump_message_binary_compat(topic, payload) -> None:
    """Preserve the historical dump hook while writing one JSONL stream."""
    dump_message_jsonl(grobro_client_module.DUMP_DIR, topic, payload)


def install_raw_dump_hook() -> None:
    """Install the legacy dump-name compatibility hook exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return

    grobro_client_module.dump_message_binary = dump_message_binary_compat
    _INSTALLED = True
    LOG.info("Installed centralized raw MQTT dump compatibility hook")
