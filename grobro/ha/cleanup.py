"""Compatibility bootstrap for Better GroBro Home Assistant runtime layers.

Small runtime adapters that only exist to patch the HA client are consolidated
here or beside their real implementation. Larger feature modules stay separate.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from threading import Lock

from grobro.ha import client as ha_client_module
from grobro.ha.config_runtime import (
    install_config_runtime,
    persisted_config_data,
    restore_config_cache_by_filename,
)
from grobro.ha.discovery_runtime import (
    clean_discovery_payload,
    configuration_url_for_ip,
    configured_local_ip,
    configured_serial,
    discovery_signature,
    install_discovery_runtime,
    migration_set,
)
from grobro.ha.neo_power_runtime import install_neo_power_runtime
from grobro.ha.time_sync_runtime import (
    install_time_sync_runtime,
    schedule_next_time_sync,
    seconds_until_next_time_sync,
    sync_supported_clocks,
)
from grobro.ha.timer_runtime import (
    cancel_runtime_timers,
    daemon_timer,
    install_timer_runtime,
)
from grobro.model.device_family import get_device_type_name, get_known_registers

LOG = logging.getLogger(__name__)
_INSTALLED = False
_BASE_GET_BAT_NUMBER = ha_client_module._get_bat_number


@lru_cache(maxsize=256)
def get_bat_number_cached(name: str):
    return _BASE_GET_BAT_NUMBER(name)


def detect_bat_count(payload: dict) -> int:
    bat_cnt = payload.get("bat_cnt")
    if isinstance(bat_cnt, int) and 1 <= bat_cnt <= 4:
        return bat_cnt

    nexa_count = payload.get("batteryPackageQuantity")
    if (
        isinstance(nexa_count, (int, float))
        and not isinstance(nexa_count, bool)
        and float(nexa_count).is_integer()
        and 1 <= int(nexa_count) <= 4
    ):
        return int(nexa_count)

    count = 1
    for bat_num in range(2, 5):
        value = payload.get(f"bat{bat_num}_ser_part_1")
        if value is not None and str(value).strip("\x00 "):
            count = bat_num
    return count


def resolve_max_bat(device_id: str, payload: dict | None = None) -> int:
    if isinstance(ha_client_module.MAX_BAT, int):
        return max(1, min(4, ha_client_module.MAX_BAT))
    if payload is not None:
        count = detect_bat_count(payload)
        ha_client_module._MAX_BAT_CACHE[device_id] = count
        return count
    return ha_client_module._MAX_BAT_CACHE.get(device_id, 1)


def install_battery_runtime_helpers() -> None:
    """Expose the common family/battery helpers on the upstream-compatible module."""
    ha_client_module.get_known_registers = get_known_registers
    ha_client_module.get_device_type_name = get_device_type_name
    ha_client_module._get_bat_number = get_bat_number_cached
    ha_client_module._detect_bat_count = detect_bat_count
    ha_client_module._resolve_max_bat = resolve_max_bat


def install_pv_runtime() -> None:
    """Limit dynamic PV-count detection to families that support it."""
    from grobro.model.device_family import uses_dynamic_pv_count

    client_cls = ha_client_module.Client
    original_detect_pv_count = client_cls._Client__detect_neo_pv_count

    def detect_pv_count_clean(self, device_id: str, payload: dict):
        if not uses_dynamic_pv_count(device_id):
            return None
        return original_detect_pv_count(self, device_id, payload)

    client_cls._Client__detect_neo_pv_count = detect_pv_count_clean


def initialize_instance_state(client) -> None:
    """Create all mutable runtime caches per HA client instance."""
    client._config_cache = {}
    client._discovery_cache = []
    client._discovery_signature = {}
    client._discovery_payload_cache = {}
    client._last_state_payload = {}
    client._last_holding_state = {}
    client._device_timers = {}
    client._device_last_seen = {}
    client._device_timer_lock = Lock()
    client._last_availability = {}
    client._last_energy_values = {}
    client._config_read_queues = {}
    client._config_read_inflight = {}
    client._config_read_timers = {}
    client._read_all_active = set()
    client._config_read_lock = Lock()
    client._migration_done = set()
    client._neo_inverter_power_read_requested = set()
    client._time_sync_timer = None


def install_state_runtime() -> None:
    """Initialize mutable HA runtime state for every client instance."""
    client_cls = ha_client_module.Client
    original_init = client_cls.__init__

    def init_with_state(self, *args, **kwargs):
        initialize_instance_state(self)
        return original_init(self, *args, **kwargs)

    client_cls.__init__ = init_with_state


def clear_reconnect_caches(client) -> None:
    """Invalidate caches that must be rebuilt after an MQTT reconnect."""
    getattr(client, "_last_availability", {}).clear()
    getattr(client, "_discovery_signature", {}).clear()
    getattr(client, "_discovery_payload_cache", {}).clear()
    getattr(client, "_last_state_payload", {}).clear()
    getattr(client, "_last_holding_state", {}).clear()
    getattr(client, "_neo_inverter_power_read_requested", set()).clear()

    discovery_cache = getattr(client, "_discovery_cache", None)
    if discovery_cache is not None:
        discovery_cache.clear()


def publish_availability(client, device_id: str, online: bool) -> bool:
    """Publish availability only when the state actually changes."""
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


def install_availability_runtime() -> None:
    """Install reconnect-cache and availability behavior on the HA client."""
    client_cls = ha_client_module.Client
    original_on_connect = client_cls._Client__on_connect

    def on_connect_clean(self, client, userdata, flags, reason_code, properties):
        clear_reconnect_caches(self)
        return original_on_connect(self, client, userdata, flags, reason_code, properties)

    client_cls._Client__on_connect = on_connect_clean

    def publish_availability_clean(self, device_id: str, online: bool):
        return publish_availability(self, device_id, online)

    client_cls._Client__publish_availability = publish_availability_clean


# Backwards-compatible helper aliases retained intentionally.
_get_bat_number_cached = get_bat_number_cached
_detect_bat_count = detect_bat_count
_resolve_max_bat = resolve_max_bat
_configured_serial = configured_serial
_configured_local_ip = configured_local_ip
_configuration_url_for_ip = configuration_url_for_ip
_persisted_config_data = persisted_config_data
_initialize_instance_state = initialize_instance_state
_restore_config_cache_by_filename = restore_config_cache_by_filename
_cancel_runtime_timers = cancel_runtime_timers
_migration_set = migration_set
_discovery_signature = discovery_signature
_daemon_timer = daemon_timer
_seconds_until_next_time_sync = seconds_until_next_time_sync
_sync_supported_clocks = sync_supported_clocks
_sync_noah_clocks = sync_supported_clocks
_schedule_next_time_sync = schedule_next_time_sync
_clean_discovery_payload = clean_discovery_payload
_clear_reconnect_caches = clear_reconnect_caches
_publish_availability = publish_availability


def install_ha_cleanup_hook() -> None:
    """Install Better GroBro HA compatibility behavior exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return

    install_battery_runtime_helpers()
    install_state_runtime()
    install_config_runtime(migration_set)
    install_time_sync_runtime()
    install_pv_runtime()
    install_availability_runtime()
    install_timer_runtime()
    install_neo_power_runtime()
    install_discovery_runtime(resolve_max_bat)

    _INSTALLED = True
    LOG.info("Installed GroBro Home Assistant compatibility runtime")
