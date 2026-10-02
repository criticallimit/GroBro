from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from grobro.ha import neo_power_runtime, time_sync_runtime


@pytest.mark.parametrize("module, schedule, field", [
    (neo_power_runtime, neo_power_runtime.schedule_known_neo_state_probe, "_neo_startup_probe_timer"),
    (time_sync_runtime, time_sync_runtime.schedule_next_time_sync, "_time_sync_timer"),
])
@pytest.mark.parametrize("stage", ["construction", "start"])
@pytest.mark.parametrize("error", [RuntimeError, OSError])
def test_optional_timer_failure_leaves_runtime_retryable(monkeypatch, module, schedule, field, stage, error):
    client = SimpleNamespace(_config_cache={})
    old = MagicMock()
    setattr(client, field, old)
    failed_timer = MagicMock()
    factory = MagicMock(return_value=failed_timer)
    if stage == "construction":
        factory.side_effect = error("thread resource unavailable")
    else:
        failed_timer.start.side_effect = error("thread resource unavailable")
    monkeypatch.setattr(module, "daemon_timer", factory)
    schedule(client)
    old.cancel.assert_called_once()
    assert getattr(client, field) is None

    retry = MagicMock()
    factory.side_effect = None
    factory.return_value = retry
    schedule(client)
    assert getattr(client, field) is retry
    retry.start.assert_called_once()
