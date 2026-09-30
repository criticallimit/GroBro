from types import SimpleNamespace
from unittest.mock import MagicMock

from grobro.ha import client as ha_client_module
from grobro.ha.timer_runtime import (
    cancel_runtime_timers,
    daemon_timer,
    effective_device_timeout,
)


def test_daemon_timer_is_daemon():
    timer = daemon_timer(60, lambda: None)
    assert timer.daemon is True
    timer.cancel()


def test_cancel_runtime_timers_cancels_and_clears_state():
    device_timer = MagicMock()
    config_timer = MagicMock()
    sync_timer = MagicMock()
    client = SimpleNamespace(
        _device_timers={"dev": device_timer},
        _config_read_timers={"cfg": config_timer},
        _device_last_seen={"dev": 1.0},
        _time_sync_timer=sync_timer,
    )

    cancel_runtime_timers(client)

    device_timer.cancel.assert_called_once()
    config_timer.cancel.assert_called_once()
    sync_timer.cancel.assert_called_once()
    assert client._device_timers == {}
    assert client._config_read_timers == {}
    assert client._device_last_seen == {}
    assert client._time_sync_timer is None


def test_effective_device_timeout_follows_report_interval(monkeypatch):
    monkeypatch.setattr(ha_client_module, "DEVICE_TIMEOUT", 120)
    client = SimpleNamespace(
        _config_cache={
            "QMNTEST": SimpleNamespace(data_interval="5"),
        }
    )

    # 5 minutes + 20% jitter allowance = 6 minutes.
    assert effective_device_timeout(client, "QMNTEST") == 360


def test_effective_device_timeout_keeps_configured_minimum(monkeypatch):
    monkeypatch.setattr(ha_client_module, "DEVICE_TIMEOUT", 300)
    client = SimpleNamespace(
        _config_cache={
            "QMNTEST": SimpleNamespace(data_interval="1"),
        }
    )

    assert effective_device_timeout(client, "QMNTEST") == 300


def test_effective_device_timeout_ignores_invalid_interval(monkeypatch):
    monkeypatch.setattr(ha_client_module, "DEVICE_TIMEOUT", 120)
    client = SimpleNamespace(
        _config_cache={
            "QMNTEST": SimpleNamespace(data_interval="invalid"),
        }
    )

    assert effective_device_timeout(client, "QMNTEST") == 120
