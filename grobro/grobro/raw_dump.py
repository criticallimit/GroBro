"""Single-file raw MQTT dump support for Better GroBro."""

from __future__ import annotations

import base64
import json
import logging
import os
import time

LOG = logging.getLogger(__name__)
from grobro.grobro.diagnostic_io import append_lines


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

        append_lines(file_path, line + "\n")
    except (OSError, TypeError, ValueError) as exc:
        LOG.error("Failed to dump message for topic %s: %s", topic, exc)

def install_raw_dump_hook() -> None:
    """Backward-compatible no-op; Client writes directly through dump_message_jsonl."""
    return None
