"""Backward-compatible Home Assistant helper aliases for Better GroBro."""

from __future__ import annotations

from threading import Lock

from grobro.ha import client as ha_client_module
from grobro.ha.discovery_runtime import (
    clean_discovery_payload,
    configured_local_ip,
    configured_serial,
)
from grobro.ha.time_sync_runtime import seconds_until_next_time_sync, sync_supported_clocks



def initialize_instance_state(client) -> None:
    """Compatibility helper for tests/tools; mirrors Client.__init__ state only."""
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
    client._config_read_queues = {}
    client._config_read_inflight = {}
    client._config_read_timers = {}
    client._read_all_active = set()
    client._config_read_lock = Lock()
    client._migration_done = set()
    client._neo_inverter_power_read_requested = set()
    client._time_sync_timer = None
    client._neo_startup_probe_timer = None


def clear_reconnect_caches(client) -> None:
    """Compatibility helper matching the direct reconnect path in Client."""
    getattr(client, "_last_availability", {}).clear()
    getattr(client, "_discovery_signature", {}).clear()
    getattr(client, "_discovery_payload_cache", {}).clear()
    getattr(client, "_last_state_payload", {}).clear()
    getattr(client, "_state_publish_cache", {}).clear()
    getattr(client, "_last_holding_state", {}).clear()
    getattr(client, "_neo_inverter_power_read_requested", set()).clear()
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
