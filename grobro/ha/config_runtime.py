"""Home Assistant config-cache persistence helpers."""

from __future__ import annotations

import os

from grobro.ha import client as ha_client_module
from grobro.ha.device_inventory import observe_device

_PERSIST_EXCLUDE = {"password", "raw"}
_STABLE_DEVICE_FIELDS = {
    "serial_number",
    "device_type",
    "model_id",
    "sw_version",
    "hw_version",
    "mac_address",
    "protocol_version",
}


def persisted_config_data(config) -> dict:
    """Return only stable device metadata that matters across restarts.

    FE19 full-config packets also contain volatile values such as clock/network
    runtime data. Those must not trigger repeated disk writes or HA discovery
    rebuilds when the actual device identity/version did not change.
    """
    if config is None:
        return {}
    return config.model_dump(
        include=_STABLE_DEVICE_FIELDS,
        exclude_none=True,
        exclude=_PERSIST_EXCLUDE,
    )


def _merge_config(previous, incoming):
    """Preserve known values when a later device config packet is partial."""
    if previous is None:
        return incoming

    merged = previous.model_dump(exclude_none=True)
    merged.update(incoming.model_dump(exclude_none=True))
    return ha_client_module.model.DeviceConfig(**merged)


def restore_device_inventory_from_config_cache(client) -> None:
    """Mirror already-restored config devices into the live Ingress inventory."""
    for device_id in getattr(client, "_config_cache", {}):
        observe_device(device_id)


def restore_config_cache_by_filename(client) -> None:
    prefix = "config_"
    suffix = ".json"
    try:
        filenames = os.listdir(".")
    except OSError:
        return
    for filename in filenames:
        if not (filename.startswith(prefix) and filename.endswith(suffix)):
            continue
        mqtt_device_id = filename[len(prefix) : -len(suffix)]
        if not mqtt_device_id:
            continue
        config = ha_client_module.model.DeviceConfig.from_file(filename)
        if config is not None:
            client._config_cache[mqtt_device_id] = config
            observe_device(mqtt_device_id)
