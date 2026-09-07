import json
from types import SimpleNamespace

from grobro.ha import client as ha_client_module
from grobro.ha.cleanup import install_ha_cleanup_hook


def test_neo_inverter_power_is_present_in_final_device_discovery(monkeypatch, tmp_path):
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

    # Avoid unrelated config-file/device-metadata work. The discovery component
    # generation itself remains the real Client implementation.
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

    discovery = json.loads(discovery_messages[-1])
    component = discovery["cmps"]["grobro_QMNTEST_cmd_inverter_power"]

    assert component["platform"] == "switch"
    assert component["name"] == "Inverter Power"
    assert component["command_topic"] == (
        "homeassistant/switch/grobro/QMNTEST/inverter_power/set"
    )
    assert component["state_topic"] == (
        "homeassistant/switch/grobro/QMNTEST/inverter_power/get"
    )
