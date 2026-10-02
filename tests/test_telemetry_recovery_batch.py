from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from grobro import ha, model
from grobro.ha import client as ha_client_module, timer_runtime
from grobro.model.growatt_registers import HomeAssistantInputRegister


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client"):
        client = ha.Client(model.MQTTConfig(host="localhost", port=1883))
    client._client.publish.return_value = (0, None)
    yield client
    client.stop()


@pytest.mark.parametrize("stage", ["construction", "start"])
@pytest.mark.parametrize("error", [RuntimeError, OSError])
def test_timeout_timer_failure_does_not_drop_live_telemetry(client, monkeypatch, stage, error):
    monkeypatch.setattr(ha_client_module, "DEVICE_TIMEOUT", 120)
    monkeypatch.setattr(client, "_Client__publish_device_discovery", MagicMock())
    timer = MagicMock()
    factory = MagicMock(return_value=timer)
    if stage == "construction":
        factory.side_effect = error("cannot allocate thread")
    else:
        timer.start.side_effect = error("cannot allocate thread")
    monkeypatch.setattr(timer_runtime, "daemon_timer", factory)
    state = HomeAssistantInputRegister(device_id="0PVPTEST", payload={"Ppv": 100})
    client.publish_input_register(state)
    assert "0PVPTEST" not in client._device_timers
    assert any(call.args[0].endswith("/state") for call in client._client.publish.call_args_list)

    retry = MagicMock()
    factory.side_effect = None
    factory.return_value = retry
    client.publish_input_register(state)
    assert client._device_timers["0PVPTEST"] is retry
    retry.start.assert_called_once()


@pytest.mark.parametrize("failure", [(4, None), SimpleNamespace(rc=15)])
@pytest.mark.parametrize("suffix", ["serial", "type"])
@pytest.mark.parametrize("cached", [False, True])
def test_failed_discovery_metadata_is_retryable(client, monkeypatch, suffix, cached, failure):
    device = "0PVPTEST"
    publish = MagicMock(return_value=(0, None))
    monkeypatch.setattr(client, "_publish_discovery_message", publish)
    monkeypatch.setattr(client, "_Client__migrate_entity_discovery", MagicMock())
    discovery = client._Client__publish_device_discovery
    if cached:
        discovery(device, 1)
        client._discovery_signature.clear()
    def reject_metadata(topic, *args, **kwargs):
        return failure if topic.endswith("/" + suffix) else (0, None)
    publish.side_effect = reject_metadata
    discovery(device, 1)
    assert device not in client._discovery_signature
    assert device in client._discovery_payload_cache

    publish.side_effect = None
    publish.reset_mock()
    discovery(device, 1)
    assert device in client._discovery_signature
    assert any(call.args[0].endswith("/" + suffix) for call in publish.call_args_list)
    assert not any(call.args[0].endswith("/config") for call in publish.call_args_list)
    publish.reset_mock()
    discovery(device, 1)
    publish.assert_not_called()
