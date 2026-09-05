"""
Home Assistant extension for GroBro to act as a MQTT bridge
between source and target MQTT brokers.
Reads Growatt MQTT packets, decodes them, maps registers
and republishes values for Home Assistant auto-discovery.
"""

import logging
import os
import signal
import time

from grobro import ha, model, grobro
from grobro.grobro.cleanup import install_grobro_cleanup_hook
from grobro.grobro.register_debug import install_register_debug_hook
from grobro.ha.cleanup import install_ha_cleanup_hook
from grobro.ha.system_time_cleanup import install_system_time_entity_cleanup

# Setup Logger
LOG_LEVEL = os.getenv("LOG_LEVEL", "ERROR").upper()
try:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
except Exception as exc:  # pylint: disable=broad-exception-caught
    logging.basicConfig(
        level=logging.ERROR,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    print(f"Failed to setup logger {exc} USING DEFAULT LOG Level(Error)")
LOG = logging.getLogger(__name__)

# Install compatibility cleanups and optional passive register logger before
# clients start processing messages.
install_grobro_cleanup_hook()
install_ha_cleanup_hook()
install_system_time_entity_cleanup()
install_register_debug_hook()

# Configuration from environment variables
GROBRO_MQTT_CONFIG = model.MQTTConfig.from_env(
    prefix="SOURCE",
    defaults=model.MQTTConfig(host="localhost", port=1883),
)
HA_MQTT_CONFIG = model.MQTTConfig.from_env(
    prefix="TARGET",
    defaults=GROBRO_MQTT_CONFIG,
)
FORWARD_MQTT_CONFIG = model.MQTTConfig.from_env(
    prefix="FORWARD",
    defaults=model.MQTTConfig(host="mqtt.growatt.com", port=7006),
)


class SignalHandler:
    """Catch SIGINT/SIGTERM and trigger graceful shutdown."""

    def __init__(self):
        self._running = True
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, _, __):
        LOG.info("Signal received, shutting down...")
        self._running = False

    @property
    def caught(self) -> bool:
        """Return whether the main loop should keep running."""
        return self._running


if __name__ == "__main__":
    ha_client = ha.Client(HA_MQTT_CONFIG)
    grobro_client = grobro.Client(GROBRO_MQTT_CONFIG, FORWARD_MQTT_CONFIG)

    # setup com: grobro -> ha
    grobro_client.on_input_register = ha_client.publish_input_register
    grobro_client.on_holding_register_input = ha_client.publish_holding_register_input
    grobro_client.on_config = ha_client.set_config
    grobro_client.on_config_read_response = ha_client.handle_config_read_response

    # setup com: ha -> grobro
    ha_client.on_command = grobro_client.send_command
    ha_client.on_config_read = grobro_client.send_config_read_message
    ha_client.on_config_command = (
        lambda dev, reg, val: grobro_client.send_config_message(dev, reg, val)
    )

    signal_handler = SignalHandler()

    ha_client.start()
    grobro_client.start()

    try:
        while signal_handler.caught:
            time.sleep(0.1)
    finally:
        ha_client.stop()
        grobro_client.stop()
        LOG.info("Stopped both clients. Exiting...")
