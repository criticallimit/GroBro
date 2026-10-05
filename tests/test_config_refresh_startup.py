"""Startup/reconnect reads share Read All's sequence without racing MQTT."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from grobro import grobro, ha, model
from grobro.ha_bridge import wire_clients


class Timer:
    def __init__(self, delay, callback):
        self.callback = callback
        self.cancelled = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        # Deliberately allow cancelled callbacks to model cancellation races.
        self.callback()


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("grobro.ha.client.Timer", Timer)
    with patch("paho.mqtt.client.Client", side_effect=lambda *args, **kwargs: MagicMock()):
        config = model.MQTTConfig(host="localhost", port=1883)
        target = ha.Client(config)
        source = grobro.Client(config, config)
    wire_clients(target, source)
    source._client.is_connected.return_value = True
    source._client.publish.return_value = (0, None)
    target._client.publish.return_value = (0, None)
    target.on_command = MagicMock()
    try:
        yield target, source
    finally:
        target.stop()
        source.stop()


def ready(source):
    source._Client__on_subscribe(source._client, None, 1, [0], None)


@pytest.mark.parametrize("device", ["0PVPTEST", "QMNTEST", "RAQTEST", "PTQTEST", "0HVRTEST"])
def test_startup_waits_for_source_subscription_and_reads_all_config(clients, device):
    target, source = clients
    target._config_cache[device] = model.DeviceConfig(serial_number=device)
    with patch("grobro.ha.neo_power_runtime.schedule_known_neo_state_probe"):
        target._Client__recover_after_home_assistant_restart(target._client)
    assert not target._read_all_active
    source._client.publish.assert_not_called()

    ready(source)
    reads = []
    target.on_config_read = lambda dev, reg: reads.append((dev, reg))
    target._read_all_start_timers[device].fire()
    expected = [reg.growatt.register_no for reg in model.get_known_registers(device).config_registers.values()]
    for register in expected:
        assert target._config_read_inflight[device] == register
        target.handle_config_read_response(device, register)
    assert reads == [(device, register) for register in expected]
    assert expected.count(76) == 1
    assert not target._read_all_active
    assert not target._config_read_queues
    assert not target._config_read_timers
    assert not target._read_all_start_timers


def test_new_device_refreshes_once_and_read_all_remains_available(clients):
    target, source = clients
    ready(source)
    device = "QMNTEST"
    config = model.DeviceConfig(serial_number=device)
    target.set_config(device, config)
    first = target._read_all_start_timers[device]
    target.set_config(device, config)
    assert target._read_all_start_timers[device] is first
    target.on_config_read = lambda dev, reg: target.handle_config_read_response(dev, reg)
    first.fire()
    target.set_config(device, config)
    assert not target._read_all_start_timers

    message = SimpleNamespace(topic=f"homeassistant/button/grobro/{device}/read_all/set", payload=b"1")
    target._Client__on_message(target._client, None, message)
    target.on_command.assert_called()
    assert device in target._read_all_start_timers


def test_reconnect_replaces_interrupted_queue_and_ignores_old_timers(clients):
    target, source = clients
    device = "QMNTEST"
    target._config_cache[device] = model.DeviceConfig(serial_number=device)
    ready(source)
    target._read_all_start_timers[device].fire()
    old_timeout = target._config_read_timers[device]
    source._Client__on_disconnect(source._client, None, None, 1, None)
    assert not source.config_reads_ready()
    ready(source)
    new_start = target._read_all_start_timers[device]
    old_timeout.fire()
    assert target._read_all_start_timers[device] is new_start
    assert not target._config_read_inflight
    new_start.fire()
    assert target._config_read_inflight[device] == 4


def test_publish_failure_retries_on_live_config_and_stop_cancels_retry(clients):
    target, source = clients
    ready(source)
    device = "QMNTEST"
    config = model.DeviceConfig(serial_number=device)
    target.set_config(device, config)
    source._client.publish.return_value = (4, None)
    target._read_all_start_timers[device].fire()
    assert device not in target._config_refresh_started
    assert not target._read_all_active
    source._client.publish.return_value = (0, None)
    target.set_config(device, config)
    timer = target._read_all_start_timers[device]
    source._client.publish.reset_mock()
    target.stop()
    timer.fire()
    ready(source)
    source._client.publish.assert_not_called()
    assert not target._read_all_active


def test_timer_start_failure_releases_all_sequence_state(clients):
    target, source = clients
    ready(source)
    with patch.object(Timer, "start", side_effect=RuntimeError("cannot start thread")):
        with pytest.raises(RuntimeError):
            target._Client__queue_all_config_reads("QMNTEST")
    assert not target._read_all_active
    assert not target._config_refresh_started
    assert not target._config_read_queues
    assert not target._read_all_start_timers


def test_rejected_subscription_does_not_start_reads(clients):
    target, source = clients
    source._Client__on_subscribe(source._client, None, 1, [128], None)
    target.set_config("QMNTEST", model.DeviceConfig(serial_number="QMNTEST"))
    assert not source.config_reads_ready()
    assert not target._read_all_active
