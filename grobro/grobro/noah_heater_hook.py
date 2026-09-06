"""Runtime hook applying validated NOAH heater state to HA telemetry."""

from __future__ import annotations

import logging

from grobro.grobro import client as grobro_client_module
from grobro.grobro.noah_heater import heater_state_from_packet

LOG = logging.getLogger(__name__)
_INSTALLED = False


def install_noah_heater_hook() -> None:
    """Install the validated NOAH heater telemetry override exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return

    client_cls = grobro_client_module.Client
    original_on_message = client_cls._Client__on_message

    def on_message_with_heater(self, client, userdata, msg):
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

    client_cls._Client__on_message = on_message_with_heater
    _INSTALLED = True
    LOG.info("Installed validated NOAH heater compatibility hook")
