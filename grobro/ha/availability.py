"""Home Assistant availability and reconnect-state helpers."""

from __future__ import annotations

import logging

from grobro.ha import client as ha_client_module

LOG = logging.getLogger(__name__)


def clear_reconnect_caches(client) -> None:
    """Invalidate caches that must be rebuilt after an MQTT reconnect."""
    getattr(client, "_last_availability", {}).clear()
    getattr(client, "_discovery_signature", {}).clear()
    getattr(client, "_discovery_payload_cache", {}).clear()
    getattr(client, "_last_state_payload", {}).clear()

    discovery_cache = getattr(client, "_discovery_cache", None)
    if discovery_cache is not None:
        discovery_cache.clear()


def publish_availability(client, device_id: str, online: bool) -> bool:
    """Publish availability only when the state actually changes.

    Returns True when MQTT was published and False when the cached state already
    matched the requested state.
    """
    availability = getattr(client, "_last_availability", None)
    if availability is None:
        availability = {}
        client._last_availability = availability

    if availability.get(device_id) is online:
        return False

    client._client.publish(
        f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/availability",
        "online" if online else "offline",
        retain=True,
    )
    if ha_client_module.AVAILABILITY_SENSOR:
        client._client.publish(
            f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/online",
            "ON" if online else "OFF",
            retain=True,
        )

    availability[device_id] = online
    return True
