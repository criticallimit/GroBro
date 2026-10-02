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
_PERSISTED_RUNTIME_FIELDS = _STABLE_DEVICE_FIELDS | {"data_interval", "local_ip"}


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


def persisted_runtime_data(config) -> dict:
    """Persist stable identity plus values consumed after a process restart."""
    if config is None:
        return {}
    return config.model_dump(include=_PERSISTED_RUNTIME_FIELDS, exclude_none=True)


def discovery_config_data(config) -> dict:
    data = persisted_config_data(config)
    if config is not None:
        data["local_ip"] = config.local_ip
    return data


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


def load_persisted_config(client, path: str):
    """Reuse parsed metadata while detecting external edits and atomic replaces."""
    absolute = os.path.abspath(path)
    try:
        stat = os.stat(absolute)
    except OSError:
        # Missing/unreadable files must remain retryable.
        getattr(client, "_persisted_config_snapshots", {}).pop(absolute, None)
        return ha_client_module.model.DeviceConfig.from_file(path)
    signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
    snapshots = getattr(client, "_persisted_config_snapshots", None)
    if snapshots is None:
        snapshots = client._persisted_config_snapshots = {}
    cached = snapshots.get(absolute)
    if cached is not None and cached[0] == signature:
        return cached[1]
    config = ha_client_module.model.DeviceConfig.from_file(path)
    if config is not None:
        snapshots[absolute] = (signature, config)
    else:
        snapshots.pop(absolute, None)
    return config


def persist_device_config(client, device_id: str, config) -> bool:
    """Keep live metadata usable while retrying transient persistence failures."""
    dirty = getattr(client, "_dirty_device_configs", None)
    if dirty is None:
        dirty = client._dirty_device_configs = set()
    try:
        config.to_file(f"config_{device_id}.json")
    except OSError:
        if device_id not in dirty:
            ha_client_module.LOG.exception("Could not persist device information for %s; will retry", device_id)
        dirty.add(device_id)
        return False
    dirty.discard(device_id)
    return True


def retry_pending_device_config(client, device_id: str) -> None:
    if device_id in getattr(client, "_dirty_device_configs", ()):
        config = client._config_cache.get(device_id)
        if config is not None:
            persist_device_config(client, device_id, config)
