from types import SimpleNamespace

from grobro.ha import client as ha_client_module
from grobro.ha.cleanup import install_ha_cleanup_hook


def test_repeated_discovery_is_skipped_until_signature_changes(monkeypatch):
    install_ha_cleanup_hook()

    published = []

    class FakeMqtt:
        def publish(self, topic, payload=None, *args, **kwargs):
            published.append((topic, payload, args, kwargs))
            return SimpleNamespace()

    device_id = "0PVPTEST"
    client = object.__new__(ha_client_module.Client)
    client._client = FakeMqtt()
    client._config_cache = {}
    client._discovery_payload_cache = {}
    client._discovery_cache = []
    client._discovery_signature = {}
    client._neo_pv_count = {}
    client._migration_done = set()

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

    publish_discovery = client._Client__publish_device_discovery
    publish_discovery(device_id, 1)
    first_publish_count = len(published)
    assert first_publish_count > 0

    publish_discovery(device_id, 1)
    assert len(published) == first_publish_count

    client._neo_pv_count[device_id] = 4
    publish_discovery(device_id, 1)
    assert len(published) > first_publish_count
