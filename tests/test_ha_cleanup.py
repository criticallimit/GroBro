import json
from types import SimpleNamespace

from grobro.ha.cleanup import (
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


def test_configured_serial_prefers_config_and_keeps_device_id_fallback():
    client = SimpleNamespace(_config_cache={})
    assert _configured_serial(client, "0PVPTEST") == "0PVPTEST"

    client._config_cache["0PVPTEST"] = SimpleNamespace(serial_number="SERIAL-NEW")
    assert _configured_serial(client, "0PVPTEST") == "SERIAL-NEW"


def test_availability_topic_always_goes_offline(monkeypatch):
    install_ha_cleanup_hook()
    monkeypatch.setattr(ha_client_module, "AVAILABILITY_SENSOR", True)

    published = []

    class FakeMqtt:
        def publish(self, topic, payload=None, *args, **kwargs):
            published.append((topic, payload, kwargs))
            return SimpleNamespace()

    client = object.__new__(ha_client_module.Client)
    client._client = FakeMqtt()

    client._Client__publish_availability("0PVPTEST", False)

    assert (
        "homeassistant/grobro/0PVPTEST/availability",
        "offline",
        {"retain": True},
    ) in published
    assert any(
        topic == "homeassistant/grobro/0PVPTEST/online" and payload == "OFF"
        for topic, payload, _ in published
    )


def test_cleanup_keeps_device_sn_entity_and_fixes_origin(monkeypatch):
    install_ha_cleanup_hook()

    published = []

    class FakeMqtt:
        def publish(self, topic, payload=None, *args, **kwargs):
            published.append((topic, payload, args, kwargs))
            return SimpleNamespace()

    client = object.__new__(ha_client_module.Client)
    client._client = FakeMqtt()
    client._config_cache = {
        "0PVPTEST": SimpleNamespace(
            serial_number="SERIAL-NEW",
            sw_version="19.19.14",
        )
    }
    client._discovery_payload_cache = {}
    client._discovery_cache = []
    client._neo_pv_count = {}

    device_id = "0PVPTEST"

    original = ha_client_module.Client._Client__publish_device_discovery

    monkeypatch.setattr(
        ha_client_module,
        "get_known_registers",
        lambda _: SimpleNamespace(
            holding_registers={},
            config_registers={},
            input_registers={},
        ),
    )
    monkeypatch.setattr(
        ha_client_module,
        "_resolve_max_bat",
        lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(
        ha_client_module.Client,
        "_Client__migrate_entity_discovery",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        ha_client_module.Client,
        "_Client__device_info_from_config",
        lambda *_args, **_kwargs: {
            "identifiers": [device_id],
            "serial_number": device_id,
        },
    )

    original(client, device_id, 1)

    discovery_payloads = [
        payload
        for topic, payload, *_ in published
        if topic == f"homeassistant/device/{device_id}/config" and payload
    ]
    assert discovery_payloads

    data = json.loads(discovery_payloads[-1])
    assert f"grobro_{device_id}_serial" in data["cmps"]
    assert data["o"]["url"] == "https://github.com/criticallimit/GroBro"

    serial_values = [
        payload
        for topic, payload, *_ in published
        if topic == f"homeassistant/grobro/{device_id}/serial"
    ]
    assert serial_values
    assert serial_values[-1] == "SERIAL-NEW"
