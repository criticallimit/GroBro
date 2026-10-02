"""Reject settings that cannot form valid MQTT connections or topics."""
from unittest.mock import MagicMock

import pytest

from grobro.ha import supervisor_config as config


@pytest.mark.parametrize("key", ["SOURCE_MQTT_HOST", "TARGET_MQTT_HOST"])
@pytest.mark.parametrize("value", ["", None, " \t "])
def test_empty_broker_host_is_rejected_before_any_supervisor_write(monkeypatch, key, value):
    request = MagicMock()
    monkeypatch.setattr(config, "_supervisor_request", request)
    with pytest.raises(config.SupervisorConfigError):
        config.save_addon_options({key: value})
    request.assert_not_called()


@pytest.mark.parametrize("value", ["#", "+", "home/#", "home/+", "bad\x00topic", "bad\ud800topic"])
def test_invalid_discovery_prefix_is_rejected_before_any_supervisor_write(monkeypatch, value):
    request = MagicMock()
    monkeypatch.setattr(config, "_supervisor_request", request)
    with pytest.raises(config.SupervisorConfigError):
        config.save_addon_options({"HA_BASE_TOPIC": value})
    request.assert_not_called()


@pytest.mark.parametrize("host", ["localhost", "homeassistant.local", "192.168.1.2", "::1"])
def test_normal_hosts_and_password_whitespace_remain_supported(host):
    assert config.normalize_options({"SOURCE_MQTT_HOST": host, "SOURCE_MQTT_PASS": " secret "}) == {
        "SOURCE_MQTT_HOST": host, "SOURCE_MQTT_PASS": " secret ",
    }


@pytest.mark.parametrize("prefix", ["", "homeassistant", "custom/homeassistant", "$ha", "haus/geräte"])
def test_valid_mqtt_prefixes_are_not_restricted_to_a_single_level(prefix):
    assert config.normalize_options({"HA_BASE_TOPIC": prefix}) == {"HA_BASE_TOPIC": prefix}
