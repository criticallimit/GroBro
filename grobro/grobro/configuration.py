"""Bridge configuration loading helpers.

Keep environment-to-MQTT configuration construction separate from the executable
entrypoint while preserving the existing prefixes and fallback relationships.
"""

from grobro import model


def load_bridge_mqtt_configs():
    """Return source, HA target and Growatt forward MQTT configurations."""
    source = model.MQTTConfig.from_env(
        prefix="SOURCE",
        defaults=model.MQTTConfig(host="localhost", port=1883),
    )
    target = model.MQTTConfig.from_env(
        prefix="TARGET",
        defaults=source,
    )
    forward = model.MQTTConfig.from_env(
        prefix="FORWARD",
        defaults=model.MQTTConfig(host="mqtt.growatt.com", port=7006),
    )
    return source, target, forward
