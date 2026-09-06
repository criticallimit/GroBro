from types import SimpleNamespace

from grobro.ha.runtime_state import initialize_instance_state


def test_runtime_state_is_created_per_instance():
    first = SimpleNamespace()
    second = SimpleNamespace()

    initialize_instance_state(first)
    initialize_instance_state(second)

    assert first._config_cache == {}
    assert first._discovery_cache == []
    assert first._discovery_signature == {}
    assert first._discovery_payload_cache == {}
    assert first._last_state_payload == {}
    assert first._last_availability == {}
    assert first._last_energy_values == {}
    assert first._config_read_queues == {}
    assert first._config_read_inflight == {}
    assert first._config_read_timers == {}
    assert first._migration_done == set()
    assert first._time_sync_timer is None

    first._config_cache["dev"] = object()
    first._last_state_payload["dev"] = "payload"

    assert second._config_cache == {}
    assert second._last_state_payload == {}
    assert first._device_timer_lock is not second._device_timer_lock
    assert first._config_read_lock is not second._config_read_lock
