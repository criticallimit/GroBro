"""Better GroBro fork-specific runtime compatibility hooks.

Core protocol handling, cloud filtering, config packet building, device-family
selection, MQTT property parsing and shutdown logic live in the hardened core.
This module intentionally contains only the small runtime hooks still needed to
attach Better GroBro behavior to the core client.
"""

from __future__ import annotations

import logging

from grobro.grobro import client as grobro_client_module
from grobro.grobro.noah_heater import heater_state_from_packet
from grobro.grobro.raw_dump import dump_message_jsonl

LOG = logging.getLogger(__name__)
_INSTALLED = False

# Compatibility alias for existing tests/extensions. Protocol interpretation
# itself lives in noah_heater.py.
_noah_heater_state_from_packet = heater_state_from_packet


def _dump_message_binary_safe(topic, payload) -> None:
    """Compatibility wrapper around the centralized single-file raw dumper."""
    dump_message_jsonl(grobro_client_module.DUMP_DIR, topic, payload)


def install_grobro_cleanup_hook() -> None:
    """Install only fork-specific runtime behavior before clients are created."""
    global _INSTALLED
    if _INSTALLED:
        return

    client_cls = grobro_client_module.Client

    # Preserve the historical dump hook name while routing it to the centralized
    # append-only JSONL dumper. The client can later call raw_dump directly.
    grobro_client_module.dump_message_binary = _dump_message_binary_safe

    # Preserve the existing NOAH Heater HA entity, but replace its unreliable R17
    # state with the heater byte from the validated cyclic 0x0104 status frame.
    original_on_message = client_cls._Client__on_message

    def on_message_clean(self, client, userdata, msg):
        device_id = grobro_client_module._extract_device_id(getattr(msg, "topic", ""))
        heater_state = heater_state_from_packet(getattr(msg, "payload", None), device_id)
        original_input_callback = getattr(self, "on_input_register", None)

        if heater_state is None or not callable(original_input_callback):
            return original_on_message(self, client, userdata, msg)

        def input_register_with_heater(state):
            if state.device_id == device_id:
                state.payload["heater"] = heater_state
            return original_input_callback(state)

        self.on_input_register = input_register_with_heater
        try:
            return original_on_message(self, client, userdata, msg)
        finally:
            self.on_input_register = original_input_callback

    client_cls._Client__on_message = on_message_clean
    _INSTALLED = True
    LOG.info("Installed GroBro fork runtime layer")
