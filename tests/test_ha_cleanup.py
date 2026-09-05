import json
from types import SimpleNamespace

from grobro.ha.cleanup import _detect_bat_count, install_ha_cleanup_hook
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


def test_cleanup_removes_duplicate_device_sn_and_fixes_origin(monkeypatch):
    install_ha_cleanup_hook()

    published = []

    class FakeMqtt:
        def publish(self, topic, payload=None, *args, **kwargs):
            published.append((topic, payload, args, kwargs))
            return SimpleNamespace()

    client = object.__new__(ha_client_module.Client)
    client._client = FakeMqtt()
    client._config_cache = {}
    client._discovery_payload_cache = {}
    client._discovery_cache = []
    client._neo_pv_count = {}

    device_id = "0PVPTEST"

    # Exercise only the wrapper behavior by replacing the cached original method
    # through a minimal discovery call environment.
    original = ha_client_module.Client._Client__publish_device_discovery

    # The installed wrapper delegates to the original upstream method, which
    # expects register/config state. Patch those dependencies minimally.
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
    assert f"grobro_{device_id}_serial" not in data["cmps"]
    assert data["o"]["url"] == "https://github.com/criticallimit/GroBro"
