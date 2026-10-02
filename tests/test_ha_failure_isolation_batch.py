from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from grobro import ha, model
from grobro.ha import client as ha_client_module
from grobro.model.growatt_registers import (
    HomeAssistantInputRegister, HomeAssistantHoldingRegisterInput,
    HomeAssistantHoldingRegisterValue, HomeAssistantHoldingRegister,
)


def holding():
    definition = HomeAssistantHoldingRegister(name="Setting", publish=True, type="number")
    return HomeAssistantHoldingRegisterInput(device_id="QMNTEST", payload=[
        HomeAssistantHoldingRegisterValue(name="first", value=1, register=definition),
        HomeAssistantHoldingRegisterValue(name="second", value=2, register=definition),
    ])


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ha_client_module, "DEVICE_TIMEOUT", 120)
    with patch("paho.mqtt.client.Client"):
        client = ha.Client(model.MQTTConfig(host="localhost", port=1883))
    client._client.publish.return_value = (0, None)
    monkeypatch.setattr(client, "_Client__reset_device_timer", MagicMock())
    monkeypatch.setattr(client, "_Client__publish_device_discovery", MagicMock())
    yield client
    client.stop()


@pytest.mark.parametrize("error", [RuntimeError, OSError])
@pytest.mark.parametrize("path", ["input", "holding", "config", "read_response"])
def test_failed_availability_does_not_drop_independent_work(client, monkeypatch, path, error):
    availability = MagicMock(side_effect=error("MQTT unavailable"))
    monkeypatch.setattr(client, "_Client__publish_availability", availability)
    if path == "input":
        client.publish_input_register(HomeAssistantInputRegister(device_id="QMNTEST", payload={"Ppv": 10}))
        assert any(call.args[0].endswith("/state") for call in client._client.publish.call_args_list)
    elif path == "holding":
        client.publish_holding_register_input(holding())
        assert len(client._last_holding_state) == 2
    elif path == "config":
        client.set_config("QMNTEST", model.DeviceConfig(serial_number="QMNTEST", sw_version="1.2.3"))
        assert client._config_cache["QMNTEST"].sw_version == "1.2.3"
        assert model.DeviceConfig.from_file("config_QMNTEST.json").sw_version == "1.2.3"
    else:
        client._config_read_inflight["QMNTEST"] = 76
        client._config_read_queues["QMNTEST"] = deque([5])
        timer = MagicMock()
        client._config_read_timers["QMNTEST"] = timer
        kickoff = MagicMock()
        monkeypatch.setattr(client, "_Client__kickoff_next_config_read", kickoff)
        client.handle_config_read_response("QMNTEST", 76)
        assert "QMNTEST" not in client._config_read_inflight
        timer.cancel.assert_called_once()
        kickoff.assert_called_once_with("QMNTEST")
    client._Client__reset_device_timer.assert_called_once_with("QMNTEST")
    # A later successful availability attempt remains possible.
    availability.side_effect = None
    client.publish_input_register(HomeAssistantInputRegister(device_id="QMNTEST", payload={"Ppv": 10}))
    assert availability.call_count == 2


@pytest.mark.parametrize("error", [RuntimeError, OSError])
def test_discovery_exception_does_not_drop_current_telemetry(client, error):
    client._Client__publish_device_discovery.side_effect = error("MQTT unavailable")
    state = HomeAssistantInputRegister(device_id="QMNTEST", payload={"Ppv": 10})
    client.publish_input_register(state)
    assert any(call.args[0].endswith("/state") for call in client._client.publish.call_args_list)
    client._Client__publish_device_discovery.side_effect = None
    client.publish_input_register(state)
    assert client._Client__publish_device_discovery.call_count == 2
    assert len([call for call in client._client.publish.call_args_list if call.args[0].endswith("/state")]) == 1


@pytest.mark.parametrize("error", [RuntimeError, OSError])
def test_one_failed_holding_publish_does_not_skip_other_values(client, monkeypatch, error):
    monkeypatch.setattr(client, "_Client__publish_availability", MagicMock())
    client._client.publish.side_effect = [error("MQTT unavailable"), (0, None)]
    client.publish_holding_register_input(holding())
    assert client._client.publish.call_count == 2
    assert ("QMNTEST", "first") not in client._last_holding_state
    assert client._last_holding_state[("QMNTEST", "second")] == 2
    client._client.publish.side_effect = None
    client._client.publish.reset_mock()
    client.publish_holding_register_input(holding())
    assert client._client.publish.call_count == 1
    assert client._client.publish.call_args.args[0].endswith("/first/get")
    assert client._last_holding_state[("QMNTEST", "first")] == 1
