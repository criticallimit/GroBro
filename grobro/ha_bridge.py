"""
Home Assistant extension for Better GroBro.

The executable entrypoint deliberately owns the small bootstrap concerns directly:
logging, environment configuration, runtime installation, callback wiring and
client lifecycle. Protocol, Home Assistant discovery, performance and persistence
logic remain in focused modules.
"""

import logging
import os

from grobro import grobro, ha, model
from grobro.grobro.noah_heater import install_noah_heater_hook
from grobro.grobro.noah_traffic_debug import install_noah_traffic_debug_hook
from grobro.grobro.raw_dump import install_raw_dump_hook
from grobro.grobro.register_debug import install_register_debug_hook
from grobro.grobro.signals import SignalHandler
from grobro.ha.cleanup import install_ha_cleanup_hook
from grobro.ha.firmware_runtime import install_firmware_runtime
from grobro.ha.mac_runtime import install_mac_runtime
from grobro.ha.performance import install_ha_performance_hook

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"


def configure_logging():
    """Configure logging with the established LOG_LEVEL fallback behavior."""
    log_level = os.getenv("LOG_LEVEL", "ERROR").upper()
    try:
        logging.basicConfig(level=log_level, format=_LOG_FORMAT)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logging.basicConfig(level=logging.ERROR, format=_LOG_FORMAT)
        print(f"Failed to setup logger {exc} USING DEFAULT LOG Level(Error)")
    return log_level, logging.getLogger("grobro.ha_bridge")


def load_bridge_mqtt_configs():
    """Return source, HA target and Growatt forward MQTT configurations."""
    source = model.MQTTConfig.from_env(
        prefix="SOURCE",
        defaults=model.MQTTConfig(host="localhost", port=1883),
    )
    target = model.MQTTConfig.from_env(prefix="TARGET", defaults=source)
    forward = model.MQTTConfig.from_env(
        prefix="FORWARD",
        defaults=model.MQTTConfig(host="mqtt.growatt.com", port=7006),
    )
    return source, target, forward


def install_runtime_layers() -> None:
    """Install permanent compatibility and performance layers in stable order."""
    install_raw_dump_hook()
    install_noah_heater_hook()
    install_ha_cleanup_hook()
    install_ha_performance_hook()
    install_mac_runtime()
    # Install last because it must wrap the final HA publish/discovery paths.
    install_firmware_runtime()


def install_optional_diagnostics() -> None:
    """Install passive diagnostics using their existing feature gates."""
    install_register_debug_hook()
    install_noah_traffic_debug_hook()


def wire_clients(ha_client, grobro_client) -> None:
    """Connect GroBro and Home Assistant callbacks bidirectionally."""
    grobro_client.on_input_register = ha_client.publish_input_register
    grobro_client.on_holding_register_input = ha_client.publish_holding_register_input
    grobro_client.on_config = ha_client.set_config
    grobro_client.on_config_read_response = ha_client.handle_config_read_response

    ha_client.on_command = grobro_client.send_command
    ha_client.on_config_read = grobro_client.send_config_read_message
    ha_client.on_config_command = (
        lambda dev, reg, val: grobro_client.send_config_message(dev, reg, val)
    )


def run_clients(ha_client, grobro_client, signal_handler) -> None:
    """Start both clients, wait for shutdown, and always stop both cleanly."""
    ha_client.start()
    grobro_client.start()
    try:
        signal_handler.wait()
    finally:
        ha_client.stop()
        grobro_client.stop()


LOG_LEVEL, LOG = configure_logging()

# Install permanent runtime hardening first, then optional passive diagnostics.
install_runtime_layers()
install_optional_diagnostics()

GROBRO_MQTT_CONFIG, HA_MQTT_CONFIG, FORWARD_MQTT_CONFIG = load_bridge_mqtt_configs()


if __name__ == "__main__":
    ha_client = ha.Client(HA_MQTT_CONFIG)
    grobro_client = grobro.Client(GROBRO_MQTT_CONFIG, FORWARD_MQTT_CONFIG)
    wire_clients(ha_client, grobro_client)
    run_clients(ha_client, grobro_client, SignalHandler())
    LOG.info("Stopped both clients. Exiting...")
