"""Install passive full-traffic capture around GroBro's NOAH MQTT paths."""

from __future__ import annotations

import logging

from grobro.grobro import client as client_module
from grobro.grobro import parser
from grobro.grobro.noah_traffic_debug import capture_noah_mqtt_traffic

LOG = logging.getLogger(__name__)
_INSTALLED = False


def _device_id_from_topic(topic: str) -> str:
    try:
        return client_module._extract_device_id(str(topic))
    except Exception:
        return ""


def _safe_unscramble(payload):
    try:
        return parser.unscramble(payload)
    except Exception:
        return None


def install_noah_traffic_debug_hook() -> None:
    """Capture all NOAH traffic already flowing through GroBro."""
    global _INSTALLED
    if _INSTALLED:
        return

    # REGISTER_DEBUG is checked again by the writer, so this hook is inert for
    # normal users while remaining available in the diagnostic fork.
    original_device_message = client_module.Client._Client__on_message
    original_cloud_message = client_module.Client._Client__on_message_forward_client
    original_publish_checked = client_module._publish_checked

    def device_message(self, client, userdata, msg):
        device_id = _device_id_from_topic(msg.topic)
        if device_id.startswith("0PVP"):
            capture_noah_mqtt_traffic(
                device_id=device_id,
                direction="device_to_grobro",
                topic=msg.topic,
                payload=msg.payload,
                decoded=_safe_unscramble(msg.payload),
                qos=getattr(msg, "qos", None),
                retain=getattr(msg, "retain", None),
                forwarded_for=client_module.get_property(msg, "forwarded-for"),
            )
        return original_device_message(self, client, userdata, msg)

    def cloud_message(self, client, userdata, msg):
        device_id = _device_id_from_topic(msg.topic)
        if device_id.startswith("0PVP"):
            capture_noah_mqtt_traffic(
                device_id=device_id,
                direction="cloud_to_grobro",
                topic=msg.topic,
                payload=msg.payload,
                decoded=_safe_unscramble(msg.payload),
                qos=getattr(msg, "qos", None),
                retain=getattr(msg, "retain", None),
                forwarded_for=client_module.get_property(msg, "forwarded-for"),
            )
        return original_cloud_message(self, client, userdata, msg)

    def publish_checked(client, topic: str, payload=None, **kwargs):
        device_id = _device_id_from_topic(topic)
        if device_id.startswith("0PVP") and payload is not None and "/33/" in str(topic):
            properties = kwargs.get("properties")
            if properties is client_module.MQTT_PROP_FORWARD_GROWATT:
                direction = "grobro_to_device_from_cloud"
            elif properties is client_module.MQTT_PROP_FORWARD_HA:
                direction = "grobro_to_device_from_ha"
            else:
                direction = "grobro_to_cloud_or_device"
            capture_noah_mqtt_traffic(
                device_id=device_id,
                direction=direction,
                topic=topic,
                payload=payload,
                decoded=_safe_unscramble(payload),
                qos=kwargs.get("qos"),
                retain=kwargs.get("retain"),
                forwarded_for=None,
            )
        return original_publish_checked(client, topic, payload, **kwargs)

    client_module.Client._Client__on_message = device_message
    client_module.Client._Client__on_message_forward_client = cloud_message
    client_module._publish_checked = publish_checked
    _INSTALLED = True
    LOG.warning("Passive full NOAH MQTT traffic capture hook installed")
