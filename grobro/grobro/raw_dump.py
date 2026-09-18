"""Single-file raw MQTT dump support for Better GroBro."""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time

LOG = logging.getLogger(__name__)
_DUMP_LOCK = threading.Lock()


def dump_message_jsonl(dump_dir: str, topic, payload) -> None:
    """Append one raw MQTT message to ``messages.jsonl``.

    Payload bytes are preserved losslessly as base64. The function intentionally
    does not parse, filter or mutate MQTT data so the dump remains suitable for
    later protocol analysis.
    """
    try:
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise TypeError("payload must be bytes-like")

        raw = bytes(payload)
        root = os.path.abspath(str(dump_dir))
        os.makedirs(root, exist_ok=True)
        file_path = os.path.abspath(os.path.join(root, "messages.jsonl"))
        if os.path.commonpath([root, file_path]) != root:
            raise ValueError("resolved dump path escaped dump directory")

        record = {
            "captured_at_ms": int(time.time() * 1000),
            "topic": str(topic),
            "payload_length": len(raw),
            "payload_encoding": "base64",
            "payload_base64": base64.b64encode(raw).decode("ascii"),
        }
        line = json.dumps(record, separators=(",", ":"))

        with _DUMP_LOCK, open(file_path, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")
    except (OSError, TypeError, ValueError) as exc:
        LOG.error("Failed to dump message for topic %s: %s", topic, exc)


# Runtime compatibility hook lives beside the dump implementation to avoid a
# one-function wrapper module.
from grobro.grobro import client as grobro_client_module

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
