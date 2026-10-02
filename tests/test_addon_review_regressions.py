"""Regression tests from the second full add-on review."""
import json
import urllib.error
import urllib.request
from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from grobro import grobro, ha, model
from grobro.ha import supervisor_config
from grobro.ha.battery_ingress import start_battery_ingress_server


@pytest.mark.parametrize("invalid", [b'{"options":"\xff"}', b"[1,2]", b"broken"])
def test_ingress_rejects_invalid_body_and_keeps_serving(tmp_path, monkeypatch, invalid):
    monkeypatch.chdir(tmp_path)
    server = start_battery_ingress_server(0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = urllib.request.Request(base + "/api/config", data=invalid, method="POST")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=3)
        assert error.value.code == 400
        assert "error" in json.loads(error.value.read())
        with urllib.request.urlopen(base + "/api/state", timeout=3) as response:
            assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()


def test_supervisor_invalid_utf8_is_controlled_error(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    with patch("urllib.request.urlopen") as request:
        request.return_value.__enter__.return_value.read.return_value = b'{"data":"\xff"}'
        with pytest.raises(supervisor_config.SupervisorConfigError):
            supervisor_config._supervisor_request("GET", "/addons/self/info")


@pytest.mark.parametrize("value", [1.5, float("inf"), float("nan"), {}, []])
def test_integer_options_reject_lossy_or_nonfinite_values(value):
    with pytest.raises(supervisor_config.SupervisorConfigError):
        supervisor_config.normalize_options({"TARGET_MQTT_PORT": value})


@pytest.mark.parametrize("value", [{"host": "example"}, ["example"]])
def test_text_options_reject_structures(value):
    with pytest.raises(supervisor_config.SupervisorConfigError):
        supervisor_config.normalize_options({"SOURCE_MQTT_HOST": value})


def test_valid_integer_and_password_options_still_preserved():
    assert supervisor_config.normalize_options({"TARGET_MQTT_PORT": "1883", "SOURCE_MQTT_PASS": " secret "}) == {
        "TARGET_MQTT_PORT": 1883, "SOURCE_MQTT_PASS": " secret ",
    }


def test_saving_options_rejects_invalid_supervisor_info(monkeypatch):
    request = MagicMock(return_value=["unexpected"])
    monkeypatch.setattr(supervisor_config, "_supervisor_request", request)
    with pytest.raises(supervisor_config.SupervisorConfigError):
        supervisor_config.save_addon_options({"TARGET_MQTT_PORT": 1883})
    request.assert_called_once_with("GET", "/addons/self/info")


@pytest.mark.parametrize("client_type", [ha.Client, grobro.Client])
@pytest.mark.parametrize("password", ["", None, " secret "])
def test_mqtt_username_is_sent_even_without_password(tmp_path, monkeypatch, client_type, password):
    monkeypatch.chdir(tmp_path)
    config = model.MQTTConfig(host="localhost", port=1883, username="user", password=password)
    with patch("paho.mqtt.client.Client") as mqtt:
        if client_type is ha.Client:
            client_type(config)
        else:
            client_type(config, config)
    mqtt.return_value.username_pw_set.assert_called_once_with("user", password)


@pytest.mark.parametrize("failure", ["disconnect", "loop_stop"])
def test_source_stop_cleans_every_connection_after_failure(tmp_path, monkeypatch, failure):
    monkeypatch.chdir(tmp_path)
    config = model.MQTTConfig(host="localhost", port=1883)
    with patch("paho.mqtt.client.Client"):
        client = grobro.Client(config, config)
    first, second = MagicMock(), MagicMock()
    client._forward_clients = {"one": first, "two": second}
    client._forward_ready = {"one": object()}
    client._forward_pending = {"one": deque([("topic", b"data", 0, False)])}
    client._pending_config_writes = {"dev": deque([4])}
    getattr(client._client, failure).side_effect = RuntimeError("source failure")
    getattr(first, failure).side_effect = RuntimeError("cloud failure")
    client.stop()
    for connection in (client._client, first, second):
        connection.disconnect.assert_called_once()
        connection.loop_stop.assert_called_once()
    assert not client._forward_clients
    assert not client._forward_ready
    assert not client._forward_pending
    assert not client._pending_config_writes


def test_nested_ha_prefix_uses_configured_serial_and_firmware(tmp_path, monkeypatch):
    from grobro.ha import client as module
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "HA_BASE_TOPIC", "site/homeassistant")
    config = model.MQTTConfig(host="localhost", port=1883)
    with patch("paho.mqtt.client.Client"):
        client = ha.Client(config)
    client._config_cache["RAQTEST"] = model.DeviceConfig(serial_number="PTQTEST", sw_version="1.2.3")
    client._publish_discovery_message("site/homeassistant/grobro/RAQTEST/serial", "RAQTEST", retain=True)
    client._client.publish.assert_called_with("site/homeassistant/grobro/RAQTEST/serial", "PTQTEST", retain=True)
    client._publish_discovery_message("site/homeassistant/grobro/RAQTEST/sw_version", "RAQTEST", retain=True)
    client._client.publish.assert_called_with("site/homeassistant/grobro/RAQTEST/sw_version", "1.2.3", retain=True)



@pytest.fixture
def target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = model.MQTTConfig(host="localhost", port=1883)
    with patch("paho.mqtt.client.Client"):
        client = ha.Client(config)
    client._client.publish.return_value = (0, None)
    return client


def test_failed_final_discovery_publish_does_not_mark_batch_complete(target):
    device = "QMNTEST"
    topic = f"homeassistant/device/{device}/config"
    payload = json.dumps({"dev": {"identifiers": [device]}, "cmps": {}})
    def publish(topic, payload, **kwargs):
        if device not in target._legacy_discovery_cleanup_done:
            # The initial config is accepted, but the final refresh fails.
            count = getattr(publish, "count", 0)
            if topic == f"homeassistant/device/{device}/config":
                publish.count = count + 1
                return (4 if count == 2 else 0, None)
        return (0, None)
    target._client.publish.side_effect = publish
    assert target._publish_discovery_message(topic, payload, retain=True)[0] != 0
    assert device not in target._legacy_discovery_cleanup_done
    target._client.publish.side_effect = None
    assert target._publish_discovery_message(topic, payload, retain=True)[0] == 0
    assert device in target._legacy_discovery_cleanup_done


def test_failed_legacy_cleanup_is_retried(target):
    device = "QMNTEST"
    def publish(topic, payload, **kwargs):
        return (4 if topic.endswith("_set_wirk/config") and payload == "" else 0, None)
    target._client.publish.side_effect = publish
    target._Client__publish_device_discovery(device)
    assert device not in target._discovery_cache
    assert device not in target._legacy_discovery_cleanup_done
    target._client.publish.side_effect = None
    target._Client__publish_device_discovery(device)
    assert device in target._discovery_cache
    assert device in target._legacy_discovery_cleanup_done


def test_failed_migration_retries_even_with_cached_device_discovery(target):
    device = "QMNTEST"
    def publish(topic, payload, **kwargs):
        return (4 if payload == '{"migrate_discovery": true}' else 0, None)
    target._client.publish.side_effect = publish
    target._Client__publish_device_discovery(device)
    assert device in target._discovery_cache
    assert device not in target._migration_done
    target._client.publish.side_effect = None
    target._client.publish.reset_mock()
    target._Client__publish_device_discovery(device)
    assert device in target._migration_done
    assert any(call.args[1] == '{"migrate_discovery": true}' for call in target._client.publish.call_args_list)
