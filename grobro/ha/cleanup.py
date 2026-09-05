"""Compatibility and cleanup layer for the Home Assistant bridge.

Keeps upstream GroBro behavior and Home Assistant entity identities stable while
correcting legacy runtime behavior in this debug fork.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
from threading import Lock

from grobro.ha import client as ha_client_module

LOG = logging.getLogger(__name__)
_INSTALLED = False
FORK_URL = "https://github.com/criticallimit/GroBro"
_PERSIST_EXCLUDE = {"password", "raw"}


def _detect_bat_count(payload: dict) -> int:
    bat_cnt = payload.get("bat_cnt")
    if isinstance(bat_cnt, int) and 1 <= bat_cnt <= 4:
        return bat_cnt
    count = 1
    for bat_num in range(2, 5):
        value = payload.get(f"bat{bat_num}_ser_part_1")
        if value is not None and str(value).strip("\x00 "):
            count = bat_num
    return count


def _resolve_max_bat(device_id: str, payload: dict | None = None) -> int:
    if isinstance(ha_client_module.MAX_BAT, int):
        return max(1, min(4, ha_client_module.MAX_BAT))
    if payload is not None:
        count = _detect_bat_count(payload)
        ha_client_module._MAX_BAT_CACHE[device_id] = count
        return count
    return ha_client_module._MAX_BAT_CACHE.get(device_id, 1)


def _configured_serial(client, device_id: str) -> str:
    config = getattr(client, "_config_cache", {}).get(device_id)
    serial = getattr(config, "serial_number", None) if config else None
    if serial and str(serial).strip():
        return str(serial).strip()
    return device_id


def _configured_local_ip(client, device_id: str) -> str | None:
    """Return the validated local IP of the device/master, never the broker IP."""
    config = getattr(client, "_config_cache", {}).get(device_id)
    value = getattr(config, "local_ip", None) if config else None
    if not value:
        return None

    text = str(value).strip().strip("\x00")
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None

    if address.is_unspecified:
        return None
    return str(address)


def _configuration_url_for_ip(ip_value: str) -> str:
    """Build a valid HTTP configuration URL for IPv4 or IPv6."""
    address = ipaddress.ip_address(ip_value)
    if address.version == 6:
        return f"http://[{address}]"
    return f"http://{address}"


def _persisted_config_data(config) -> dict:
    if config is None:
        return {}
    return config.model_dump(exclude_none=True, exclude=_PERSIST_EXCLUDE)


def _initialize_instance_state(client) -> None:
    client._config_cache = {}
    client._discovery_cache = []
    client._discovery_signature = {}
    client._device_timers = {}
    client._last_energy_values = {}
    client._config_read_queues = {}
    client._config_read_inflight = {}
    client._config_read_timers = {}
    client._config_read_lock = Lock()
    client._migration_done = set()


def _restore_config_cache_by_filename(client) -> None:
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


def _cancel_runtime_timers(client) -> None:
    for timer_map_name in ("_device_timers", "_config_read_timers"):
        timer_map = getattr(client, timer_map_name, {})
        for timer in list(timer_map.values()):
            try:
                timer.cancel()
            except Exception:  # pragma: no cover
                pass
        timer_map.clear()


def _migration_set(client) -> set:
    migrations = getattr(client, "_migration_done", None)
    if migrations is None:
        migrations = set()
        client._migration_done = migrations
    return migrations


def _discovery_signature(client, device_id: str, effective_max_bat: int) -> tuple[int, int | None]:
    """Return the small subset of runtime state that changes discovery contents."""
    pv_count = getattr(client, "_neo_pv_count", {}).get(device_id)
    return effective_max_bat, pv_count


def _clean_discovery_payload(client, device_id: str, data: dict) -> dict:
    """Remove GroBro-only fields while preserving HA entity identities/topics."""
    origin = data.get("o")
    if isinstance(origin, dict):
        origin["url"] = FORK_URL

    device_meta = data.get("dev")
    if isinstance(device_meta, dict):
        # Keep identifiers unchanged so Home Assistant's device identity remains
        # stable. Correct only visible metadata.
        device_meta["serial_number"] = _configured_serial(client, device_id)

        # Home Assistant MQTT discovery has no arbitrary ip_address field in its
        # device metadata. configuration_url is the supported way to expose a
        # device-local management address in the device information card.
        local_ip = _configured_local_ip(client, device_id)
        if local_ip:
            device_meta["configuration_url"] = _configuration_url_for_ip(local_ip)
        else:
            device_meta.pop("configuration_url", None)

    components = data.get("cmps")
    if isinstance(components, dict):
        for component in components.values():
            if not isinstance(component, dict):
                continue

            # These are GroBro model/control fields, not MQTT discovery keys.
            component.pop("publish", None)
            component.pop("type", None)

            # Config entries with platform=sensor are read-only. A command topic
            # makes no sense for an MQTT sensor and can cause HA validation noise.
            if component.get("platform") == "sensor":
                component.pop("command_topic", None)

    return data


def install_ha_cleanup_hook() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    ha_client_module._detect_bat_count = _detect_bat_count
    ha_client_module._resolve_max_bat = _resolve_max_bat
    client_cls = ha_client_module.Client

    original_init = client_cls.__init__

    def init_clean(self, *args, **kwargs):
        _initialize_instance_state(self)
        result = original_init(self, *args, **kwargs)
        _restore_config_cache_by_filename(self)
        return result

    client_cls.__init__ = init_clean

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
            or _persisted_config_data(existing_config) != _persisted_config_data(config)
        ):
            LOG.info("Saving updated config for %s", device_id)
            config.to_file(config_path)
        else:
            LOG.debug("No persisted config change for %s", device_id)

        self._config_cache[device_id] = config
        if device_id in self._discovery_cache:
            self._discovery_cache.remove(device_id)
        getattr(self, "_discovery_signature", {}).pop(device_id, None)
        _migration_set(self).discard(device_id)
        self._Client__publish_device_discovery(device_id)

    client_cls.set_config = set_config_clean

    def publish_availability_clean(self, device_id: str, online: bool):
        self._client.publish(
            f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/availability",
            "online" if online else "offline",
            retain=True,
        )
        if ha_client_module.AVAILABILITY_SENSOR:
            self._client.publish(
                f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/online",
                "ON" if online else "OFF",
                retain=ha_client_module.PUBLISH_SENSORS_RETAINED,
            )

    client_cls._Client__publish_availability = publish_availability_clean

    original_stop = client_cls.stop

    def stop_clean(self):
        _cancel_runtime_timers(self)
        return original_stop(self)

    client_cls.stop = stop_clean

    original_migrate = client_cls._Client__migrate_entity_discovery

    def migrate_once(self, device_id, known_registers):
        migrations = _migration_set(self)
        if device_id in migrations:
            return
        original_migrate(self, device_id, known_registers)
        migrations.add(device_id)

    client_cls._Client__migrate_entity_discovery = migrate_once

    original_publish_discovery = client_cls._Client__publish_device_discovery

    def publish_discovery_clean(self, device_id: str, effective_max_bat=None):
        if effective_max_bat is None:
            effective_max_bat = _resolve_max_bat(device_id)

        signature = _discovery_signature(self, device_id, effective_max_bat)
        signatures = getattr(self, "_discovery_signature", None)
        if signatures is None:
            signatures = {}
            self._discovery_signature = signatures

        if device_id in self._discovery_cache and signatures.get(device_id) == signature:
            return None

        original_publish = self._client.publish

        def publish(topic, payload=None, *args, **kwargs):
            if (
                topic == f"{ha_client_module.HA_BASE_TOPIC}/device/{device_id}/config"
                and payload
            ):
                try:
                    data = json.loads(payload)
                    data = _clean_discovery_payload(self, device_id, data)
                    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
                except (TypeError, ValueError):
                    pass

            if topic == f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/serial":
                payload = _configured_serial(self, device_id)

            if topic == f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/sw_version":
                config = getattr(self, "_config_cache", {}).get(device_id)
                sw_version = getattr(config, "sw_version", None) if config else None
                if not sw_version:
                    return None
                payload = sw_version

            return original_publish(topic, payload, *args, **kwargs)

        self._client.publish = publish
        try:
            result = original_publish_discovery(self, device_id, effective_max_bat)
            signatures[device_id] = signature
            return result
        finally:
            self._client.publish = original_publish

    client_cls._Client__publish_device_discovery = publish_discovery_clean
    _INSTALLED = True
    LOG.info("Installed GroBro Home Assistant cleanup compatibility layer")
