"""Recover MQTT operations without changing successful packets or ordering."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from grobro import grobro, ha, model
from grobro.ha.neo_power_runtime import request_known_neo_states
from grobro.ha.time_sync_runtime import sync_supported_clocks
from grobro.model.growatt_registers import HomeAssistantInputRegister


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = model.MQTTConfig(host="localhost", port=1883)
    with patch("paho.mqtt.client.Client"):
        source = grobro.Client(config, config)
        target = ha.Client(config)
    yield source, target
    source.stop()
    target.stop()


@pytest.mark.parametrize("error", [RuntimeError, OSError])
def test_one_neo_probe_exception_does_not_skip_other_devices(error):
    commands = []
    def send(command):
        commands.append(command.device_id)
        if command.device_id == "QMNTEST1":
            raise error("network unavailable")
        return (0, None)
    client = SimpleNamespace(on_command=send, _config_cache={"QMNTEST1": None, "QMNTEST2": None})
    assert request_known_neo_states(client) == 1
    assert commands == ["QMNTEST1", "QMNTEST2"]
    assert client._neo_inverter_power_read_requested == {"QMNTEST2"}
    client.on_command = lambda command: (0, None)
    assert request_known_neo_states(client) == 1
    assert client._neo_inverter_power_read_requested == {"QMNTEST1", "QMNTEST2"}


@pytest.mark.parametrize("failure", [(4, None), (15, None), RuntimeError("offline"), OSError("closed")])
def test_command_subscription_failure_keeps_recovery_and_retries_on_activity(clients, failure):
    _, target = clients
    target._client.subscribe.side_effect = [failure, failure, (0, 1)]
    target._client.publish.return_value = (0, None)
    target._last_state_payload["QMNTEST"] = {"Ppv": 0}
    target._read_all_active.add("QMNTEST")
    with patch("grobro.ha.neo_power_runtime.schedule_known_neo_state_probe") as probe, patch.object(
        target, "_Client__reset_device_timer"
    ):
        target._Client__recover_after_home_assistant_restart(target._client)
        assert target._command_subscription_pending
        assert not target._last_state_payload
        assert not target._read_all_active
        probe.assert_called_once()
        target._Client__refresh_device_activity("QMNTEST")
        assert target._command_subscription_pending
        target._Client__refresh_device_activity("QMNTEST")
        assert not target._command_subscription_pending
        target._Client__refresh_device_activity("QMNTEST")
        assert target._client.subscribe.call_count == 3


@pytest.mark.parametrize("failure", [(4, None), RuntimeError("network unavailable"), OSError("closed socket")],
                         ids=["return-code", "runtime-error", "socket-error"])
def test_identical_telemetry_retries_failed_initial_neo_read(clients, monkeypatch, failure):
    _, target = clients
    monkeypatch.setattr(target, "_Client__publish_device_discovery", MagicMock())
    monkeypatch.setattr(target, "_Client__reset_device_timer", MagicMock())
    target._client.publish.return_value = (0, None)
    target.on_command = MagicMock(side_effect=[failure, (0, None)])
    state = HomeAssistantInputRegister(device_id="QMNTEST", payload={"Ppv": 0})
    target.publish_input_register(state)
    target.publish_input_register(state)
    target.publish_input_register(state)
    assert target.on_command.call_count == 2
    assert target._neo_inverter_power_read_requested == {"QMNTEST"}
    state_publishes = [call for call in target._client.publish.call_args_list if call.args[0].endswith("/state")]
    assert len(state_publishes) == 1
    assert all(call.args[0].register_no == 0 for call in target.on_command.call_args_list)


@pytest.mark.parametrize("error", [RuntimeError, OSError])
def test_cloud_publish_exception_does_not_replay_old_packet(clients, error):
    source, _ = clients
    forward = MagicMock()
    forward.publish.side_effect = [error("unavailable"), (0, None)]
    with patch("paho.mqtt.client.Client", return_value=forward):
        with pytest.raises(error):
            source._Client__publish_to_growatt_server("QMNTEST", "topic", b"old", 0, False)
        source._Client__publish_to_growatt_server("QMNTEST", "topic", b"new", 0, False)
    assert [call.kwargs["payload"] for call in forward.publish.call_args_list] == [b"old", b"new"]



@pytest.mark.parametrize("failure", [(4, None), SimpleNamespace(rc=4)])
def test_rejected_clock_publish_is_not_counted_as_synchronized(failure):
    callback = MagicMock(side_effect=[failure, (0, None)])
    client = SimpleNamespace(on_config_command=callback, _config_cache={"QMNTEST": None, "0PVPTEST": None})
    assert sync_supported_clocks(client, datetime(2026, 10, 2, 12)) == 1
    assert callback.call_count == 2
    assert all(call.args[1:] == (31, "2026-10-02 12:00:00") for call in callback.call_args_list)


@pytest.mark.parametrize("stage", ["bridge", "device"])
@pytest.mark.parametrize("error", [RuntimeError, OSError])
def test_connect_availability_error_does_not_skip_recovery(clients, stage, error):
    _, target = clients
    target._config_cache = {"QMNTEST1": None, "QMNTEST2": None}
    target._discovery_cache = ["QMNTEST1"]
    def publish(topic, *args, **kwargs):
        if (stage == "bridge" and topic == target._bridge_topic()) or (stage == "device" and topic.endswith("QMNTEST1/availability")):
            raise error("socket unavailable")
        return (0, None)
    with patch.object(target._client, "publish", side_effect=publish), patch("grobro.ha.neo_power_runtime.schedule_known_neo_state_probe") as probe:
        target._Client__on_connect(target._client, None, None, SimpleNamespace(is_failure=False), None)
        target._client.subscribe.assert_called_once()
        assert not target._discovery_cache
        probe.assert_called_once_with(target, delay=0.5)
        assert any(call.args[0].endswith("QMNTEST2/availability") for call in target._client.publish.call_args_list)


@pytest.mark.parametrize("failure", [(4, None), RuntimeError("socket unavailable"), OSError("socket unavailable")],
                         ids=["return-code", "runtime-error", "socket-error"])
def test_failed_bridge_online_publish_is_retried_on_live_device(clients, failure):
    _, target = clients
    with patch.object(target._client, "publish", side_effect=[failure, (0, None), (0, None)]), patch("grobro.ha.neo_power_runtime.schedule_known_neo_state_probe"):
        target._Client__on_connect(target._client, None, None, SimpleNamespace(is_failure=False), None)
        target._Client__publish_availability("QMNTEST", True)
        target._Client__publish_availability("QMNTEST", True)
        online = [call for call in target._client.publish.call_args_list if call.args[0] == target._bridge_topic()]
        assert len(online) == 2
        assert all(call.args[1] == "online" and call.kwargs == {"qos": 1, "retain": True} for call in online)
        assert target._last_availability["QMNTEST"] is True


def test_broker_rejected_subscription_is_retried_on_next_device_activity(clients):
    _, target = clients
    target._client.subscribe.return_value = (0, 23)
    target._Client__subscribe_commands(target._client)
    assert not target._command_subscription_pending

    # SUBACK rejection is distinct from subscribe() being accepted locally.
    target._Client__on_subscribe(target._client, None, 23, [0x80], None)
    assert target._command_subscription_pending
    target._client.subscribe.reset_mock()

    with patch.object(target, "_Client__reset_device_timer"):
        target._Client__refresh_device_activity("QMNTEST")
    target._client.subscribe.assert_called_once()
    assert not target._command_subscription_pending


def test_successful_subscription_ack_does_not_trigger_retry(clients):
    _, target = clients
    target._client.subscribe.return_value = (0, 24)
    target._Client__subscribe_commands(target._client)
    target._Client__on_subscribe(target._client, None, 24, [0, 0], None)
    assert not target._command_subscription_pending


@pytest.mark.parametrize(("device_id", "register_no", "expected_timeout"), [
    ("QMNTEST", 76, 10),
    ("0PVPTEST", 76, 10),
    ("0HVRTEST", 76, 10),
    ("QMNTEST", 4, 60),
    ("0PVPTEST", 4, 60),
    ("0HVRTEST", 4, 60),
])
def test_shared_config_read_timeout_for_neo_noah_nexa(clients, device_id, register_no, expected_timeout):
    from collections import deque

    _, target = clients
    target.config_reads_ready = lambda: True
    target.on_config_read = MagicMock(return_value=(0, None))
    target._config_read_queues[device_id] = deque([register_no])
    with patch.object(target, "_Client__start_config_read_timer") as schedule:
        target._Client__kickoff_next_config_read(device_id)
    schedule.assert_called_once()
    assert schedule.call_args.args[0] == expected_timeout
    assert schedule.call_args.args[1] == target._Client__config_read_timeout
    target.on_config_read.assert_called_once_with(device_id, register_no)


@pytest.mark.parametrize("device_id", ["QMNTEST", "0PVPTEST", "0HVRTEST"])
def test_shared_wifi_timeout_continues_queue_without_device_specific_logic(clients, device_id):
    from collections import deque

    _, target = clients
    target.config_reads_ready = lambda: True
    target.on_config_read = MagicMock(return_value=(0, None))
    target._config_read_queues[device_id] = deque([76, 4])
    with patch.object(target, "_Client__start_config_read_timer") as schedule:
        target._Client__kickoff_next_config_read(device_id)
        target._Client__config_read_timeout(device_id, 76)

    assert [call.args[1] for call in target.on_config_read.call_args_list] == [76, 4]
    assert [call.args[0] for call in schedule.call_args_list] == [10, 60]
    assert target._config_read_inflight[device_id] == 4
