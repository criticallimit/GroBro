"""Backward-compatible Home Assistant helper aliases for Better GroBro."""

from __future__ import annotations

from threading import Lock, RLock

from grobro.ha import client as ha_client_module
from grobro.ha.discovery_runtime import (
    clean_discovery_payload,
    configured_local_ip,
    configured_serial,
)
from grobro.ha.time_sync_runtime import seconds_until_next_time_sync, sync_supported_clocks



def initialize_instance_state(client) -> None:
    """Initialize the shared runtime state once for each Client instance."""
    client._config_cache = {}
    client._discovery_cache = []
    client._discovery_signature = {}
    client._discovery_payload_cache = {}
    client._last_state_payload = {}
    client._last_holding_state = {}
    client._state_publish_cache = {}
    client._smart_meter_state_cache = {}
    client._device_timers = {}
    client._device_last_seen = {}
    client._device_timer_lock = Lock()
    client._last_availability = {}
    client._config_read_queues = {}
    client._config_read_inflight = {}
    client._config_read_timers = {}
    client._read_all_start_timers = {}
    client._read_all_active = set()
    client._config_read_lock = Lock()
    client._migration_done = set()
    client._neo_inverter_power_read_requested = set()
    client._time_sync_timer = None
    client._neo_startup_probe_timer = None
    client._runtime_lock = RLock()
    client._stopped = False


def clear_reconnect_caches(client) -> None:
    """Clear transient publication state on MQTT reconnect and HA birth."""
    getattr(client, "_last_availability", {}).clear()
    getattr(client, "_discovery_signature", {}).clear()
    getattr(client, "_discovery_payload_cache", {}).clear()
    from grobro.ha.performance import _clear_state_publish_cache
    from grobro.ha.neo_power_runtime import clear_neo_inverter_power_read_cache
    _clear_state_publish_cache(client)
    getattr(client, "_smart_meter_state_cache", {}).clear()
    clear_neo_inverter_power_read_cache(client)
    discovery_cache = getattr(client, "_discovery_cache", None)
    if discovery_cache is not None:
        discovery_cache.clear()


# Backwards-compatible helper aliases for external callers/tests.
_initialize_instance_state = initialize_instance_state
_clear_reconnect_caches = clear_reconnect_caches
_configured_serial = configured_serial
_configured_local_ip = configured_local_ip
_clean_discovery_payload = clean_discovery_payload
_seconds_until_next_time_sync = seconds_until_next_time_sync
_sync_supported_clocks = sync_supported_clocks
_sync_noah_clocks = sync_supported_clocks
_detect_bat_count = ha_client_module._detect_bat_count
_resolve_max_bat = ha_client_module._resolve_max_bat


def install_ha_cleanup_hook() -> None:
    """Backward-compatible no-op; HA cleanup now runs directly in Client."""
    return None
