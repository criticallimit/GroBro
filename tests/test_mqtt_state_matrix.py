"""Cross-broker state transitions for the Better GroBro bridge.

The network clients are mocked; this checks callback contracts and cache
invariants, NOT broker delivery or real network reconnection.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from grobro.model.mqtt_config import MQTTConfig


@pytest.fixture
def clients():
    from grobro.grobro.client import Client as SourceClient
    from grobro.ha.client import Client as TargetClient
    from grobro.ha.device_inventory import clear_device_inventory

    clear_device_inventory()
    config = MQTTConfig(host="localhost", port=1883)
    with patch("grobro.grobro.client.mqtt.Client") as mock_source, patch(
        "grobro.grobro.client.Path.glob", return_value=[]
    ), patch("grobro.ha.client.mqtt.Client") as mock_target, patch(
        "grobro.ha.client.os.listdir", return_value=[]
    ):
        source = SourceClient(config, config)
        target = TargetClient(config)

    source._client = mock_source.return_value
    target._client = mock_target.return_value
    source._client.subscribe.return_value = (0, 1)
    source._client.is_connected.return_value = True
    target._client.publish.return_value = (0, None)
    target._client.subscribe.return_value = (0, 2)
    source.on_ready = MagicMock()
    # Other tests exercise recovery. This matrix isolates broker transitions.
    target._Client__recover_after_home_assistant_restart = MagicMock()
    yield source, target
    clear_device_inventory()


def _accepted():
    return SimpleNamespace(is_failure=False)


def _rejected():
    return SimpleNamespace(is_failure=True)


def test_source_requires_granted_subscription_and_current_connection(clients):
    source, target = clients
    assert source.config_reads_ready() is False
    assert target._ha_mqtt_connected is False

    source._Client__on_connect(source._client, None, None, _accepted(), None)
    assert source.config_reads_ready() is False
    source._client.subscribe.assert_called_with("c/#")

    source._Client__on_subscribe(source._client, None, 1, [128], None)
    assert source.config_reads_ready() is False
    source.on_ready.assert_not_called()

    source._Client__on_subscribe(source._client, None, 1, [0], None)
    assert source.config_reads_ready() is True
    source.on_ready.assert_called_once()

    source._client.is_connected.return_value = False
    assert source.config_reads_ready() is False
    source._Client__on_disconnect(source._client, None, None, _accepted(), None)
    assert source._config_read_ready.is_set() is False


@pytest.mark.parametrize("device", ["0PVPTEST000001", "QMNTEST0000001", "0HVRTEST000001"])
def test_ha_disconnect_blocks_device_online_independent_of_family(clients, device):
    from grobro.ha.device_inventory import get_device_inventory, observe_device_availability

    _source, target = clients
    observe_device_availability(device, True)
    target._ha_mqtt_connected = True
    target._Client__on_disconnect(target._client, None, None, _accepted(), None)

    assert target._ha_mqtt_connected is False
    assert target._bridge_online_pending is True
    target._client.publish.reset_mock()
    assert target._Client__publish_availability(device, True) is False
    target._client.publish.assert_not_called()
    assert get_device_inventory()[0]["connection_status"] == "offline"


def test_ha_rejected_connack_never_publishes_online(clients):
    _source, target = clients
    target._ha_mqtt_connected = True
    target._client.publish.reset_mock()
    target._Client__on_connect(target._client, None, None, _rejected(), None)

    assert target._ha_mqtt_connected is False
    assert target._bridge_online_pending is True
    target._client.publish.assert_not_called()
    target._Client__recover_after_home_assistant_restart.assert_not_called()


def test_successful_connack_reenables_ha_path_and_runs_recovery(clients):
    _source, target = clients
    target._Client__on_connect(target._client, None, None, _accepted(), None)

    assert target._ha_mqtt_connected is True
    target._Client__recover_after_home_assistant_restart.assert_called_once_with(target._client)
    assert target._Client__publish_availability("0PVPTEST000001", True) is True
