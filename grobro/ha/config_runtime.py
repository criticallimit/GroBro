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
    original_init = client_cls.__init__

    def init_with_restore(self, *args, **kwargs):
        result = original_init(self, *args, **kwargs)
        restore_config_cache_by_filename(self)
        return result

    client_cls.__init__ = init_with_restore

    def set_config_clean(self, device_id, config):
        config_path = f"config_{device_id}.json"
        existing_config = ha_client_module.model.DeviceConfig.from_file(config_path)
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
            or persisted_config_data(existing_config) != persisted_config_data(config)
        ):
            LOG.info("Saving updated config for %s", device_id)
            config.to_file(config_path)
        else:
            LOG.debug("No persisted config change for %s", device_id)

        self._config_cache[device_id] = config
        if device_id in self._discovery_cache:
            self._discovery_cache.remove(device_id)
        getattr(self, "_discovery_signature", {}).pop(device_id, None)
        migration_set(self).discard(device_id)
        self._Client__publish_device_discovery(device_id)

    client_cls.set_config = set_config_clean
