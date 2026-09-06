from types import SimpleNamespace
from unittest.mock import MagicMock

from grobro.ha import availability


def _client():
    return SimpleNamespace(
        _client=MagicMock(),
        _last_availability={},
        _discovery_signature={"dev": (1, None)},
        _discovery_payload_cache={"dev": "cached"},
        _last_state_payload={"dev": "payload"},
        _discovery_cache=["dev"],
    )


def test_publish_availability_skips_identical_state(monkeypatch):
    client = _client()
    monkeypatch.setattr(availability.ha_client_module, "AVAILABILITY_SENSOR", False)

    assert availability.publish_availability(client, "dev", True) is True
    assert availability.publish_availability(client, "dev", True) is False
    assert client._client.publish.call_count == 1


def test_publish_availability_updates_optional_online_sensor(monkeypatch):
    client = _client()
    monkeypatch.setattr(availability.ha_client_module, "AVAILABILITY_SENSOR", True)

    assert availability.publish_availability(client, "dev", False) is True
    calls = client._client.publish.call_args_list
    assert len(calls) == 2
    assert calls[0].args[1] == "offline"
    assert calls[1].args[1] == "OFF"
    assert calls[0].kwargs["retain"] is True
    assert calls[1].kwargs["retain"] is True


def test_reconnect_caches_are_invalidated():
    client = _client()

    availability.clear_reconnect_caches(client)

    assert client._last_availability == {}
    assert client._discovery_signature == {}
    assert client._discovery_payload_cache == {}
    assert client._last_state_payload == {}
    assert client._discovery_cache == []
