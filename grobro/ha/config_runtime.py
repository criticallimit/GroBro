"""Home Assistant config-cache persistence helpers."""

from __future__ import annotations

import logging
import os

from grobro.ha import client as ha_client_module

LOG = logging.getLogger(__name__)
_PERSIST_EXCLUDE = {"password", "raw"}


def persisted_config_data(config) -> dict:
    if config is None:
        return {}
    return config.model_dump(exclude_none=True, exclude=_PERSIST_EXCLUDE)


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


def install_config_runtime(migration_set) -> None:
    client_cls = ha_client_module.Client

    def set_config_clean(self, device_id, config):
        config_path = f"config_{device_id}.json"
        existing_config = ha_client_module.model.DeviceConfig.from_file(config_path)
        previous_config = self._config_cache.get(device_id)
        previous_discovery_data = persisted_config_data(previous_config)
        current_discovery_data = persisted_config_data(config)
        discovery_changed = previous_discovery_data != current_discovery_data

        needs_sensitive_cleanup = bool(
            existing_config
            and (
                getattr(existing_config, "password", None) is not None
                or getattr(existing_config, "raw", None) is not None
            )
        )
        if (
            existing_config is None
            or needs_sensitive_cleanup
            or persisted_config_data(existing_config) != current_discovery_data
        ):
            LOG.info("Saving updated config for %s", device_id)
            config.to_file(config_path)
        else:
            LOG.debug("No persisted config change for %s", device_id)

        self._config_cache[device_id] = config

        # Rebuild discovery only for a real discovery-relevant config change, or
        # when this device has not been discovered yet in the current broker session.
        if not discovery_changed and device_id in self._discovery_cache:
            LOG.debug("No discovery-relevant config change for %s", device_id)
            return

        if device_id in self._discovery_cache:
            self._discovery_cache.remove(device_id)
        getattr(self, "_discovery_signature", {}).pop(device_id, None)
        migration_set(self).discard(device_id)
        self._Client__publish_device_discovery(device_id)

    client_cls.set_config = set_config_clean
