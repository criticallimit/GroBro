"""Compatibility and cleanup layer for the Home Assistant bridge.

Keeps upstream GroBro behavior and Home Assistant entity identities stable while
correcting legacy runtime behavior in this fork.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import time
from datetime import datetime, timedelta
from functools import lru_cache
from threading import Lock, Timer

from grobro.ha import client as ha_client_module
from grobro.model.device_family import (
    get_device_type_name,
    get_known_registers,
    supports_time_sync,
    uses_dynamic_pv_count,
)

LOG = logging.getLogger(__name__)
_INSTALLED = False
FORK_URL = "https://github.com/criticallimit/GroBro"
_PERSIST_EXCLUDE = {"password", "raw"}
_TIME_SYNC_REGISTER = 31
_TIME_SYNC_HOURS = (0, 12)
_BASE_GET_BAT_NUMBER = ha_client_module._get_bat_number


@lru_cache(maxsize=256)
def _get_bat_number_cached(name: str):
    """Cache parsing of stable register names used on every telemetry packet."""
    return _BASE_GET_BAT_NUMBER(name)


def _daemon_timer(*args, **kwargs) -> Timer:
    """Create a Timer that never keeps the add-on process alive by itself."""
    timer = Timer(*args, **kwargs)
    timer.daemon = True
    return timer


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
    client._device_last_seen = {}
    client._device_timer_lock = Lock()
    client._last_availability = {}
    client._last_energy_values = {}
    client._config_read_queues = {}
    client._config_read_inflight = {}
    client._config_read_timers = {}
    client._config_read_lock = Lock()
    client._migration_done = set()
    client._time_sync_timer = None


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
    getattr(client, "_device_last_seen", {}).clear()

    time_sync_timer = getattr(client, "_time_sync_timer", None)
    if time_sync_timer is not None:
        try:
            time_sync_timer.cancel()
        except Exception:  # pragma: no cover
            pass
        client._time_sync_timer = None


def _migration_set(client) -> set:
    migrations = getattr(client, "_migration_done", None)
    if migrations is None:
        migrations = set()
        client._migration_done = migrations
    return migrations


def _discovery_signature(client, device_id: str, effective_max_bat: int) -> tuple[int, int | None]:
    pv_count = getattr(client, "_neo_pv_count", {}).get(device_id)
    return effective_max_bat, pv_count


def _seconds_until_next_time_sync(now: datetime | None = None) -> float:
    current = now or datetime.now()
    candidates = []
    for hour in _TIME_SYNC_HOURS:
        candidate = current.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(days=1)
        candidates.append(candidate)
    return max(1.0, (min(candidates) - current).total_seconds())


def _sync_supported_clocks(client, now: datetime | None = None) -> int:
    callback = getattr(client, "on_config_command", None)
    if not callable(callback):
        return 0

    current = now or datetime.now()
    value = current.strftime("%Y-%m-%d %H:%M:%S")
    synced = 0
    for device_id in tuple(getattr(client, "_config_cache", {})):
        if not supports_time_sync(device_id):
            continue
        try:
            callback(device_id, _TIME_SYNC_REGISTER, value)
            synced += 1
        except Exception as exc:
            LOG.warning("Automatic time sync failed for %s: %s", device_id, exc)
    if synced:
        LOG.info("Automatically synchronized time for %s Growatt device(s)", synced)
    return synced


# Backwards-compatible helper name retained for tests/older callers.
def _sync_noah_clocks(client, now: datetime | None = None) -> int:
    return _sync_supported_clocks(client, now)


def _schedule_next_time_sync(client) -> None:
    previous = getattr(client, "_time_sync_timer", None)
    if previous is not None:
        try:
            previous.cancel()
        except Exception:  # pragma: no cover
            pass

    def run_and_reschedule():
        client._time_sync_timer = None
        _sync_supported_clocks(client)
        _schedule_next_time_sync(client)

    timer = _daemon_timer(_seconds_until_next_time_sync(), run_and_reschedule)
    client._time_sync_timer = timer
    timer.start()


def _clean_discovery_payload(client, device_id: str, data: dict) -> dict:
    origin = data.get("o")
    if isinstance(origin, dict):
        origin["url"] = FORK_URL

    device_meta = data.get("dev")
    if isinstance(device_meta, dict):
        device_meta["serial_number"] = _configured_serial(client, device_id)
        local_ip = _configured_local_ip(client, device_id)
        if local_ip:
            device_meta["configuration_url"] = _configuration_url_for_ip(local_ip)
        else:
            device_meta.pop("configuration_url", None)

    components = data.get("cmps")
    if isinstance(components, dict):
        components.pop(f"grobro_{device_id}_sync_time", None)

        for component in components.values():
            if not isinstance(component, dict):
                continue
            component.pop("publish", None)
            component.pop("type", None)
            if component.get("platform") == "sensor":
                component.pop("command_topic", None)

    return data


def install_ha_cleanup_hook() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Make the central device-family registry the active source of truth for HA.
    ha_client_module.get_known_registers = get_known_registers
    ha_client_module.get_device_type_name = get_device_type_name
    ha_client_module._get_bat_number = _get_bat_number_cached
    ha_client_module._detect_bat_count = _detect_bat_count
    ha_client_module._resolve_max_bat = _resolve_max_bat
    ha_client_module.Timer = _daemon_timer
    client_cls = ha_client_module.Client

    original_init = client_cls.__init__

    def init_clean(self, *args, **kwargs):
        _initialize_instance_state(self)
        result = original_init(self, *args, **kwargs)
        _restore_config_cache_by_filename(self)
        return result

    client_cls.__init__ = init_clean

    original_start = client_cls.start

    def start_clean(self):
        result = original_start(self)
        _schedule_next_time_sync(self)
        return result

    client_cls.start = start_clean

    original_detect_pv_count = client_cls._Client__detect_neo_pv_count

    def detect_pv_count_clean(self, device_id: str, payload: dict):
        if not uses_dynamic_pv_count(device_id):
            return
        return original_detect_pv_count(self, device_id, payload)

    client_cls._Client__detect_neo_pv_count = detect_pv_count_clean

    original_on_connect = client_cls._Client__on_connect

    def on_connect_clean(self, client, userdata, flags, reason_code, properties):
        getattr(self, "_last_availability", {}).clear()
        getattr(self, "_discovery_signature", {}).clear()
        getattr(self, "_discovery_payload_cache", {}).clear()
        discovery_cache = getattr(self, "_discovery_cache", None)
        if discovery_cache is not None:
            discovery_cache.clear()
        return original_on_connect(self, client, userdata, flags, reason_code, properties)

    client_cls._Client__on_connect = on_connect_clean

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
        availability = getattr(self, "_last_availability", None)
        if availability is None:
            availability = {}
            self._last_availability = availability
        if availability.get(device_id) is online:
            return

        self._client.publish(
            f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/availability",
            "online" if online else "offline",
            retain=True,
        )
        if ha_client_module.AVAILABILITY_SENSOR:
            self._client.publish(
                f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/online",
                "ON" if online else "OFF",
                retain=True,
            )
        availability[device_id] = online

    client_cls._Client__publish_availability = publish_availability_clean

    if ha_client_module.DEVICE_TIMEOUT > 0:
        def reset_device_timer_clean(self, device_id: str):
            now = time.monotonic()
            lock = getattr(self, "_device_timer_lock", None)
            if lock is None:
                lock = Lock()
                self._device_timer_lock = lock

            def check_timeout(d_id: str):
                with lock:
                    last_seen = self._device_last_seen.get(d_id)
                    if last_seen is None:
                        self._device_timers.pop(d_id, None)
                        return
                    remaining = ha_client_module.DEVICE_TIMEOUT - (time.monotonic() - last_seen)
                    if remaining > 0:
                        timer = _daemon_timer(remaining, check_timeout, args=(d_id,))
                        self._device_timers[d_id] = timer
                        timer.start()
                        return
                    self._device_timers.pop(d_id, None)
                    self._device_last_seen.pop(d_id, None)

                LOG.warning("Device %s timed out. Mark it as unavailable.", d_id)
                self._Client__publish_availability(d_id, False)

            with lock:
                self._device_last_seen[device_id] = now
                timer = self._device_timers.get(device_id)
                if timer is not None and timer.is_alive():
                    return
                timer = _daemon_timer(ha_client_module.DEVICE_TIMEOUT, check_timeout, args=(device_id,))
                self._device_timers[device_id] = timer
                timer.start()

        client_cls._Client__reset_device_timer = reset_device_timer_clean

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
