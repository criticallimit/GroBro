"""Connection failures remain visible without logging every retry."""
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from grobro import grobro, ha, model


@pytest.mark.parametrize("client_type", [ha.Client, grobro.Client])
@pytest.mark.parametrize("failure", ["transport", "connack"])
def test_failure_logged_once_per_outage_and_successful_reconnect_resets_phase(tmp_path, monkeypatch, caplog, client_type, failure):
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client"):
        cfg = model.MQTTConfig(host="localhost", port=1883)
        target = client_type(cfg) if client_type is ha.Client else client_type(cfg, cfg)
    mqtt = target._client
    mqtt.publish.return_value = (0, None)
    mqtt.subscribe.return_value = (0, 1)
    caplog.set_level(logging.ERROR)
    try:
        with patch("grobro.ha.neo_power_runtime.schedule_known_neo_state_probe"):
            def fail():
                if failure == "transport":
                    mqtt.on_connect_fail(mqtt, None)
                else:
                    mqtt.on_connect(mqtt, None, None, SimpleNamespace(is_failure=True), None)
            fail()
            fail()
            assert len(caplog.records) == 1
            mqtt.subscribe.assert_not_called()
            mqtt.on_connect(mqtt, None, None, SimpleNamespace(is_failure=False), None)
            mqtt.subscribe.assert_called_once()
            fail()
            assert len(caplog.records) == 2
    finally:
        target.stop()
    caplog.clear()
    mqtt.subscribe.reset_mock()
    mqtt.on_connect_fail(mqtt, None)
    mqtt.on_connect(mqtt, None, None, SimpleNamespace(is_failure=False), None)
    assert not caplog.records
    mqtt.subscribe.assert_not_called()


@pytest.mark.parametrize("client_type", [ha.Client, grobro.Client])
@pytest.mark.parametrize("reasons", [[0, 128], [SimpleNamespace(is_failure=True)]])
def test_broker_subscription_rejection_is_visible_without_log_flood(tmp_path, monkeypatch, caplog, client_type, reasons):
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client"):
        cfg = model.MQTTConfig(host="localhost", port=1883)
        target = client_type(cfg) if client_type is ha.Client else client_type(cfg, cfg)
    mqtt = target._client
    caplog.set_level(logging.ERROR)
    try:
        mqtt.on_subscribe(mqtt, None, 1, reasons, None)
        mqtt.on_subscribe(mqtt, None, 2, reasons, None)
        assert len(caplog.records) == 1
        assert "broker rejected a subscription" in caplog.text
        mqtt.on_subscribe(mqtt, None, 3, [0, 1, 2], None)
        mqtt.on_subscribe(mqtt, None, 4, reasons, None)
        assert len(caplog.records) == 2
    finally:
        target.stop()
    caplog.clear()
    mqtt.on_subscribe(mqtt, None, 5, reasons, None)
    assert not caplog.records
