import json
from types import SimpleNamespace

from grobro.ha import client as ha_client_module
from grobro.ha.cleanup import install_ha_cleanup_hook


def test_neo_inverter_power_matches_upstream_discovery_path(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    install_ha_cleanup_hook()

    published = []

    class FakeMqtt:
        def publish(self, topic, payload=None, *args, **kwargs):
            published.append((topic, payload, kwargs))
            return SimpleNamespace()

    client = object.__new__(ha_client_module.Client)
    client._client = FakeMqtt()
    client._config_cache = {}
    client._discovery_cache = []
    client._discovery_signature = {}
    client._discovery_payload_cache = {}
    client._migration_done = set()
    client._neo_pv_count = {}

    client._Client__device_info_from_config = lambda _device_id: {
        "identifiers": ["QMNTEST"],
        "name": "Growatt QMNTEST",
        "manufacturer": "Growatt",
        "serial_number": "QMNTEST",
    }

    client._Client__publish_device_discovery("QMNTEST", 1)

    discovery_messages = [
        payload
        for topic, payload, _kwargs in published
        if topic == "homeassistant/device/QMNTEST/config" and payload
    ]
    assert discovery_messages

    parsed_messages = [json.loads(payload) for payload in discovery_messages]

    repair = next(
        data
        for data in parsed_messages
        if data.get("cmps", {}).get("grobro_QMNTEST_cmd_mqtt_ip")
        == {"platform": "text"}
    )
    repair_components = repair["cmps"]
    assert repair_components["grobro_QMNTEST_cmd_system_time"] == {
        "platform": "text"
    }
    assert repair_components["grobro_QMNTEST_sync_time"] == {
        "platform": "button"
    }

    # Better GroBro must never use Inverter Power as a removal/repair component.
    repaired_inverter = repair_components["grobro_QMNTEST_cmd_inverter_power"]
    assert repaired_inverter["name"] == "Inverter Power"
    assert repaired_inverter["platform"] == "switch"
    assert repaired_inverter["type"] == "switch"
    assert repaired_inverter["publish"] is True

    discovery = parsed_messages[-1]
    component = discovery["cmps"]["grobro_QMNTEST_cmd_inverter_power"]

    # These fields intentionally match Robert's GroBro-generated component.
    assert component["platform"] == "switch"
    assert component["name"] == "Inverter Power"
    assert component["type"] == "switch"
    assert component["publish"] is True
    assert component["command_topic"] == (
        "homeassistant/switch/grobro/QMNTEST/inverter_power/set"
    )
    assert component["state_topic"] == (
        "homeassistant/switch/grobro/QMNTEST/inverter_power/get"
    )

    assert "grobro_QMNTEST_cmd_mqtt_ip" not in discovery["cmps"]
    assert "grobro_QMNTEST_cmd_system_time" not in discovery["cmps"]
    assert "grobro_QMNTEST_sync_time" not in discovery["cmps"]

    # Better GroBro must not clear Robert's legacy Inverter Power discovery topics.
    assert (
        "homeassistant/switch/grobro/QMNTEST_inverter_power/config",
        "",
        {"retain": True},
    ) not in published
    assert (
        "homeassistant/switch/grobro/QMNTEST_inverter_power_read/config",
        "",
        {"retain": True},
    ) not in published
