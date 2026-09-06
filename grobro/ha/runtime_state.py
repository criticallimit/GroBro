"""Per-client Home Assistant runtime state initialization."""

from __future__ import annotations

from threading import Lock


def initialize_instance_state(client) -> None:
    """Create all mutable runtime caches per client instance.

    Keeping these containers instance-local prevents state leakage between client
    instances and makes reconnect/runtime helpers independent from class-level
    defaults.
    """
    client._config_cache = {}
    client._discovery_cache = []
    client._discovery_signature = {}
    client._discovery_payload_cache = {}
    client._last_state_payload = {}
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
