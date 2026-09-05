"""Compatibility and cleanup layer for the Home Assistant bridge.

Keeps upstream GroBro behavior and Home Assistant entity identities stable while
correcting legacy runtime behavior in this debug fork:
- battery count prefers the explicit ``bat_cnt`` register and uses a conservative
  one-battery fallback before telemetry is available;
- mutable HA client caches, timers and read queues are initialized per instance;
- persisted config files are also indexed by the MQTT device id encoded in their
  filename so a differing internal serial number does not orphan the cache;
- the existing Device SN entity keeps the same name/topic/unique id but publishes
  the configured serial number when available;
- a legacy ``sw_version`` publish that accidentally used the device id is fixed;
- MQTT discovery origin metadata points to this fork;
- the main availability topic is always updated on online/offline transitions,
  even when the optional Online binary sensor is enabled;
- outstanding timers are cancelled during client shutdown.

Device/entity identifiers and existing sensor names are intentionally unchanged.
"""

from __future__ import annotations

import json
import logging
import os
from threading import Lock

from grobro.ha import client as ha_client_module

LOG = logging.getLogger(__name__)
_INSTALLED = False
FORK_URL = "https://github.com/criticallimit/GroBro"


def _detect_bat_count(payload: dict) -> int:
    """Resolve battery count from telemetry with a conservative fallback."""
    bat_cnt = payload.get("bat_cnt")
    if isinstance(bat_cnt, int) and 1 <= bat_cnt <= 4:
        return bat_cnt

    # Battery 1 is represented by the main NOAH device id in the current map;
    # additional battery serial fragments begin at bat2_*.
    count = 1
    for bat_num in range(2, 5):
        value = payload.get(f"bat{bat_num}_ser_part_1")
        if value is not None and str(value).strip("\x00 "):
            count = bat_num
    return count


def _resolve_max_bat(device_id: str, payload: dict | None = None) -> int:
    """Resolve MAX_BAT without the legacy implicit four-battery fallback."""
    if isinstance(ha_client_module.MAX_BAT, int):
        return max(1, min(4, ha_client_module.MAX_BAT))

    if payload is not None:
        count = _detect_bat_count(payload)
        ha_client_module._MAX_BAT_CACHE[device_id] = count
        return count

    return ha_client_module._MAX_BAT_CACHE.get(device_id, 1)


def _configured_serial(client, device_id: str) -> str:
    """Return the best available serial while keeping device_id as fallback."""
    config = client._config_cache.get(device_id)
    serial = getattr(config, "serial_number", None) if config else None
    if serial and str(serial).strip():
        return str(serial).strip()
    return device_id


def _initialize_instance_state(client) -> None:
    """Create mutable HA client runtime state per instance instead of per class."""
    client._config_cache = {}
    client._discovery_cache = []
    client._device_timers = {}
    client._last_energy_values = {}
    client._config_read_queues = {}
    client._config_read_inflight = {}
    client._config_read_timers = {}
    client._config_read_lock = Lock()


def _restore_config_cache_by_filename(client) -> None:
    """Index persisted config files by their stable MQTT device-id filename."""
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
    """Cancel pending timeout/config-read timers before disconnecting."""
    for timer_map_name in ("_device_timers", "_config_read_timers"):
        timer_map = getattr(client, timer_map_name, {})
        for timer in list(timer_map.values()):
            try:
                timer.cancel()
            except Exception:  # pragma: no cover - defensive cleanup only
                pass
        timer_map.clear()


def install_ha_cleanup_hook() -> None:
    """Install narrowly scoped fixes without changing HA entity identities."""
    global _INSTALLED
    if _INSTALLED:
        return

    ha_client_module._detect_bat_count = _detect_bat_count
    ha_client_module._resolve_max_bat = _resolve_max_bat

    client_cls = ha_client_module.Client

    # Ensure all mutable state belongs to the actual Client instance. Initialize
    # it before upstream __init__ loads cached config files into _config_cache.
    original_init = client_cls.__init__

    def init_clean(self, *args, **kwargs):
        _initialize_instance_state(self)
        result = original_init(self, *args, **kwargs)
        _restore_config_cache_by_filename(self)
        return result

    client_cls.__init__ = init_clean

    # The upstream implementation suppresses the main availability=offline
    # publish when AVAILABILITY_SENSOR is enabled. All discovered entities still
    # use that availability topic, so always update it and publish the optional
    # binary sensor in addition.
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

    original_publish_discovery = client_cls._Client__publish_device_discovery

    def publish_discovery_clean(self, device_id: str, effective_max_bat=None):
        original_publish = self._client.publish

        def publish(topic, payload=None, *args, **kwargs):
            if (
                topic
                == f"{ha_client_module.HA_BASE_TOPIC}/device/{device_id}/config"
                and payload
            ):
                try:
                    data = json.loads(payload)
                    origin = data.get("o")
                    if isinstance(origin, dict):
                        origin["url"] = FORK_URL
                    payload = json.dumps(
                        data,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                except (TypeError, ValueError):
                    pass

            # Keep the existing Device SN entity/topic/unique id exactly as-is,
            # but feed it from the configured serial number when available.
            if topic == f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/serial":
                payload = _configured_serial(self, device_id)

            # Suppress the historical bogus device-id-as-software-version value.
            if (
                topic
                == f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/sw_version"
            ):
                config = self._config_cache.get(device_id)
                sw_version = getattr(config, "sw_version", None) if config else None
                if not sw_version:
                    return None
                payload = sw_version

            return original_publish(topic, payload, *args, **kwargs)

        self._client.publish = publish
        try:
            return original_publish_discovery(
                self,
                device_id,
                effective_max_bat,
            )
        finally:
            self._client.publish = original_publish

    client_cls._Client__publish_device_discovery = publish_discovery_clean
    _INSTALLED = True
    LOG.info("Installed GroBro Home Assistant cleanup compatibility layer")
