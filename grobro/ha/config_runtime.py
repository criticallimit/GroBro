"""Home Assistant config-cache persistence helpers."""

from __future__ import annotations

import logging
import os

from grobro.ha import client as ha_client_module
from grobro.ha.device_inventory import observe_device

LOG = logging.getLogger(__name__)
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


def install_config_runtime(migration_set) -> None:
    client_cls = ha_client_module.Client

    def set_config_clean(self, device_id, config):
        observe_device(device_id)
        # Receiving a real config packet is also live communication from the device.
        # Partial test/tool clients may not have an MQTT runtime attached.
        if hasattr(self, "_client") and hasattr(self, "_device_last_seen"):
            self._Client__publish_availability(device_id, True)
            if ha_client_module.DEVICE_TIMEOUT > 0:
                self._Client__reset_device_timer(device_id)

        config_path = f"config_{device_id}.json"
        existing_config = ha_client_module.model.DeviceConfig.from_file(config_path)
        previous_config = self._config_cache.get(device_id) or existing_config
        effective_config = _merge_config(previous_config, config)

        previous_stable_data = persisted_config_data(previous_config)
        current_stable_data = persisted_config_data(effective_config)
        disk_stable_data = persisted_config_data(existing_config)
        discovery_changed = previous_stable_data != current_stable_data

        needs_sensitive_cleanup = bool(
            existing_config
            and (
                getattr(existing_config, "password", None) is not None
                or getattr(existing_config, "raw", None) is not None
            )
        )

        # Persist only when stable identity/version metadata changed. Volatile
        # FE19 fields (datetime, Wi-Fi/runtime/network values, etc.) remain
        # available in the live cache but no longer cause repeated disk writes.
        if (
            existing_config is None
            or needs_sensitive_cleanup
            or disk_stable_data != current_stable_data
        ):
            LOG.info("Saving updated device metadata for %s", device_id)
            effective_config.to_file(config_path)
        else:
            LOG.debug("Device metadata unchanged for %s; skipping config save", device_id)

        self._config_cache[device_id] = effective_config

        # Rebuild discovery only for a real discovery-relevant metadata change,
        # or when this device has not been discovered yet in this broker session.
        if not discovery_changed and device_id in self._discovery_cache:
            LOG.debug("No discovery-relevant config change for %s", device_id)
            return

        if device_id in self._discovery_cache:
            self._discovery_cache.remove(device_id)
        getattr(self, "_discovery_signature", {}).pop(device_id, None)
        migration_set(self).discard(device_id)
        self._Client__publish_device_discovery(device_id)

    client_cls.set_config = set_config_clean
