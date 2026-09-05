import json
from types import SimpleNamespace

from grobro.ha.cleanup import (
    _clean_discovery_payload,
    _configured_local_ip,
    _configured_serial,
    _detect_bat_count,
    _initialize_instance_state,
    _resolve_max_bat,
    install_ha_cleanup_hook,
)
from grobro.ha import client as ha_client_module


def test_detect_bat_count_prefers_explicit_register():
    payload = {
        "bat_cnt": 3,
        "bat2_ser_part_1": "BAT2",
        "bat3_ser_part_1": "BAT3",
        "bat4_ser_part_1": "BAT4",
    }
    assert _detect_bat_count(payload) == 3


def test_detect_bat_count_falls_back_conservatively():
    assert _detect_bat_count({}) == 1
    assert _detect_bat_count({"bat2_ser_part_1": "BAT2"}) == 2
    assert _detect_bat_count({"bat3_ser_part_1": "BAT3"}) == 3


def test_resolve_max_bat_does_not_assume_four(monkeypatch):
    monkeypatch.setattr(ha_client_module, "MAX_BAT", "auto")
    ha_client_module._MAX_BAT_CACHE.clear()
    assert _resolve_max_bat("0PVPTEST") == 1
    assert _resolve_max_bat("0PVPTEST", {"bat_cnt": 3}) == 3
    assert _resolve_max_bat("0PVPTEST") == 3


def test_instance_state_is_not_shared():
    first = SimpleNamespace()
    second = SimpleNamespace()
    _initialize_instance_state(first)
    _initialize_instance_state(second)
    first._config_cache["a"] = 1
    first._discovery_cache.append("a")
    first._config_read_queues["a"] = [1]
    assert second._config_cache == {}
    assert second._discovery_cache == []
    assert second._config_read_queues == {}
    assert first._config_read_lock is not second._config_read_lock
    assert first._device_timer_lock is not second._device_timer_lock


def test_configured_serial_prefers_config_and_keeps_device_id_fallback():
    client = SimpleNamespace(_config_cache={})
    assert _configured_serial(client, "0PVPTEST") == "0PVPTEST"
    client._config_cache["0PVPTEST"] = SimpleNamespace(serial_number="SERIAL-NEW")
    assert _configured_serial(client, "0PVPTEST") == "SERIAL-NEW"


def test_configured_local_ip_uses_only_valid_local_ip():
    client = SimpleNamespace(_config_cache={"0PVPTEST": SimpleNamespace(local_ip="192.168.1.50", remote_ip="203.0.113.10")})
    assert _configured_local_ip(client, "0PVPTEST") == "192.168.1.50"
    client._config_cache["0PVPTEST"].local_ip = "not-an-ip"
    assert _configured_local_ip(client, "0PVPTEST") is None


def test_clean_discovery_payload_keeps_identity_and_removes_internal_fields():
    client = SimpleNamespace(_config_cache={"0PVPTEST": SimpleNamespace(serial_number="SERIAL-NEW", local_ip="192.168.1.50")})
    data = {
        "o": {"name": "grobro", "url": "https://github.com/robertzaage/GroBro"},
        "dev": {"identifiers": ["0PVPTEST"], "serial_number": "0PVPTEST"},
        "cmps": {
            "grobro_0PVPTEST_cmd_wifi_signal_strength": {"platform": "sensor", "name": "Wi-Fi Signal Strength", "unique_id": "grobro_0PVPTEST_cmd_wifi_signal_strength", "state_topic": "homeassistant/config/grobro/0PVPTEST/76/get", "command_topic": "homeassistant/config/grobro/0PVPTEST/76/set", "publish": True, "type": "sensor", "device_class": "signal_strength", "state_class": "measurement", "unit_of_measurement": "dBm"},
            "grobro_0PVPTEST_cmd_mqtt_port": {"platform": "number", "name": "MQTT Port", "unique_id": "grobro_0PVPTEST_cmd_mqtt_port", "state_topic": "homeassistant/config/grobro/0PVPTEST/18/get", "command_topic": "homeassistant/config/grobro/0PVPTEST/18/set", "publish": True, "type": "number"},
        },
    }
    cleaned = _clean_discovery_payload(client, "0PVPTEST", data)
    assert cleaned["dev"]["identifiers"] == ["0PVPTEST"]
    assert cleaned["dev"]["serial_number"] == "SERIAL-NEW"
    assert cleaned["dev"]["configuration_url"] == "http://192.168.1.50"
    assert cleaned["o"]["url"] == "https://github.com/criticallimit/GroBro"
    sensor = cleaned["cmps"]["grobro_0PVPTEST_cmd_wifi_signal_strength"]
    assert "command_topic" not in sensor
    assert "publish" not in sensor
    assert "type" not in sensor
    number = cleaned["cmps"]["grobro_0PVPTEST_cmd_mqtt_port"]
    assert number["command_topic"] == "homeassistant/config/grobro/0PVPTEST/18/set"


def test_availability_and_online_are_retained(monkeypatch):
    install_ha_cleanup_hook()
    monkeypatch.setattr(ha_client_module, "AVAILABILITY_SENSOR", True)
    published = []

    class FakeMqtt:
        def publish(self, topic, payload=None, *args, **kwargs):
            published.append((topic, payload, kwargs))
            return SimpleNamespace()

    client = object.__new__(ha_client_module.Client)
    client._client = FakeMqtt()
    client._last_availability = {}
    client._Client__publish_availability("0PVPTEST", True)

    assert ("homeassistant/grobro/0PVPTEST/availability", "online", {"retain": True}) in published
    assert ("homeassistant/grobro/0PVPTEST/online", "ON", {"retain": True}) in published


def test_repeated_availability_state_is_not_republished(monkeypatch):
    install_ha_cleanup_hook()
    monkeypatch.setattr(ha_client_module, "AVAILABILITY_SENSOR", True)
    published = []

    class FakeMqtt:
        def publish(self, topic, payload=None, *args, **kwargs):
            published.append((topic, payload, kwargs))
            return SimpleNamespace()

    client = object.__new__(ha_client_module.Client)
    client._client = FakeMqtt()
    client._last_availability = {}
    client._Client__publish_availability("0PVPTEST", True)
    first_count = len(published)
    client._Client__publish_availability("0PVPTEST", True)
    assert len(published) == first_count
    client._Client__publish_availability("0PVPTEST", False)
    assert len(published) > first_count


def test_mqtt_reconnect_invalidates_publish_caches():
    install_ha_cleanup_hook()
    client = object.__new__(ha_client_module.Client)
    client._last_availability = {"0PVPTEST": True}
    client._discovery_signature = {"0PVPTEST": (3, None)}
    client._discovery_payload_cache = {"0PVPTEST": "cached"}
    client._discovery_cache = ["0PVPTEST"]
    client._Client__on_connect(None, None, None, 0, None)
    assert client._last_availability == {}
    assert client._discovery_signature == {}
    assert client._discovery_payload_cache == {}
    assert client._discovery_cache == []
