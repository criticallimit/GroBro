"""A discovery refresh must never delete existing dashboard battery entities."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from grobro.ha.client import _MAX_BAT_CACHE, get_known_registers
from grobro.ha.sensor_cache import flush, merge_state


def test_startup_config_discovery_restores_persisted_bat2_bat3(ha_client, tmp_path, monkeypatch):
    device_id = "0PVP0000TEST0001"
    monkeypatch.setenv("BETTER_GROBRO_STATE_DIR", str(tmp_path))
    _MAX_BAT_CACHE.pop(device_id, None)
    writer = SimpleNamespace()
    merge_state(
        writer, device_id,
        {"bat2_temp": 21.0, "bat3_temp": 22.0},
        get_known_registers(device_id),
        detected_bat_count=3, max_bat=3,
    )
    flush(writer, force=True)

    ha_client._Client__migrate_entity_discovery = MagicMock()
    ha_client._Client__device_info_from_config = MagicMock(
        return_value={"identifiers": [device_id], "name": "Growatt NOAH"}
    )
    ha_client._publish_discovery_message = MagicMock(return_value=(0, None))
    try:
        # Configuration arrives before live input registers: saved battery
        # positions must already be present in the first device payload.
        ha_client._Client__publish_device_discovery(device_id)
        calls = [
            c for c in ha_client._publish_discovery_message.call_args_list
            if c.args[0] == f"homeassistant/device/{device_id}/config"
        ]
        assert len(calls) == 1
        assert calls[0].args[1]  # never an empty deletion payload
        components = json.loads(calls[0].args[1])["cmps"]
        for sensor in ("bat2_temp", "bat3_temp", "bat_2_soc_pct", "bat_3_soc_pct"):
            assert f"grobro_{device_id}_{sensor}" in components
    finally:
        _MAX_BAT_CACHE.pop(device_id, None)


def test_discovery_refresh_does_not_publish_empty_deletion(ha_client):
    device_id = "0PVP0000TEST0001"
    ha_client._Client__migrate_entity_discovery = MagicMock()
    ha_client._Client__device_info_from_config = MagicMock(
        return_value={"identifiers": [device_id], "name": "Growatt NOAH"}
    )
    ha_client._publish_discovery_message = MagicMock(return_value=(0, None))
    ha_client._Client__publish_device_discovery(device_id, effective_max_bat=3)
    # Simulate a firmware change / discovery metadata refresh.
    ha_client._discovery_cache.clear()
    ha_client._discovery_signature.clear()
    ha_client._discovery_payload_cache.clear()
    ha_client._Client__publish_device_discovery(device_id, effective_max_bat=3)
    topic = f"homeassistant/device/{device_id}/config"
    messages = [
        c.args[1] for c in ha_client._publish_discovery_message.call_args_list
        if c.args[0] == topic
    ]
    assert len(messages) >= 2
    assert all(message for message in messages)
    assert all(
        f"grobro_{device_id}_bat3_temp" in json.loads(message)["cmps"]
        for message in messages
    )
