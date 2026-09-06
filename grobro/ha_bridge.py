"""
Home Assistant extension for GroBro to act as a MQTT bridge
between source and target MQTT brokers.
Reads Growatt MQTT packets, decodes them, maps registers
and republishes values for Home Assistant auto-discovery.
"""

from grobro import ha, grobro
from grobro.grobro.configuration import load_bridge_mqtt_configs
from grobro.grobro.diagnostics import install_optional_diagnostics
from grobro.grobro.lifecycle import run_clients
from grobro.grobro.logging_setup import configure_logging
from grobro.grobro.runtime import install_runtime_layers
from grobro.grobro.signals import SignalHandler
from grobro.grobro.wiring import wire_clients

LOG_LEVEL, LOG = configure_logging()

# Install permanent runtime hardening first, then optional passive diagnostics.
install_runtime_layers()
install_optional_diagnostics()

# Preserve the established module-level names for compatibility/tests while
# delegating environment parsing to one focused helper.
GROBRO_MQTT_CONFIG, HA_MQTT_CONFIG, FORWARD_MQTT_CONFIG = load_bridge_mqtt_configs()


if __name__ == "__main__":
    ha_client = ha.Client(HA_MQTT_CONFIG)
    grobro_client = grobro.Client(GROBRO_MQTT_CONFIG, FORWARD_MQTT_CONFIG)
    wire_clients(ha_client, grobro_client)
    run_clients(ha_client, grobro_client, SignalHandler())
    LOG.info("Stopped both clients. Exiting...")
