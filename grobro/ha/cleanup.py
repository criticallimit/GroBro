"""Compatibility bootstrap for Better GroBro Home Assistant runtime layers.

Implementation lives in focused modules. This file retains the historical helper
names used by tests and older callers while installing the same runtime behavior
in a stable, reviewable order.
"""

from __future__ import annotations

import logging

from grobro.ha.availability import clear_reconnect_caches, publish_availability
from grobro.ha.availability_runtime import install_availability_runtime
from grobro.ha.battery_runtime import (
    detect_bat_count,
    get_bat_number_cached,
    install_battery_runtime_helpers,
    resolve_max_bat,
)
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
from grobro.ha.pv_runtime import install_pv_runtime
from grobro.ha.runtime_state import initialize_instance_state
from grobro.ha.state_runtime import install_state_runtime
from grobro.ha.time_sync_runtime import (
    install_time_sync_runtime,
    schedule_next_time_sync,
    seconds_until_next_time_sync,
    sync_supported_clocks,
)
from grobro.ha.timer_runtime import install_timer_runtime
from grobro.ha.timers import cancel_runtime_timers, daemon_timer

LOG = logging.getLogger(__name__)
_INSTALLED = False

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

    # Ordering matters: state must exist before the config wrapper restores files;
    # discovery is installed last so config/availability hooks call the final path.
    install_battery_runtime_helpers()
    install_state_runtime()
    install_config_runtime(migration_set)
    install_time_sync_runtime()
    install_pv_runtime()
    install_availability_runtime()
    install_timer_runtime()
    install_discovery_runtime(resolve_max_bat)

    _INSTALLED = True
    LOG.info("Installed GroBro Home Assistant compatibility runtime")
