from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from grobro.grobro.client import Client
from grobro.model.mqtt_config import MQTTConfig


PACKET = bytes.fromhex(
    "0001000700300119 514d4e303030425a50344e3939314d4c "
    "0000000000000000000000000000 000200 "
    "004c00042d303631 0005000131 4458"
)
DEVICE = "QMN000BZP4N991ML"


@pytest.mark.parametrize("error", [RuntimeError, OSError])
@pytest.mark.parametrize("stage", ["metadata", "read-progress"])
def test_compound_callback_failure_keeps_remaining_values(tmp_path, monkeypatch, error, stage):
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client"):
        client = Client(MQTTConfig(host="localhost", port=1883), MQTTConfig(host="localhost", port=1884))
    packet = PACKET.replace(bytes.fromhex("004c00042d303631"), bytes.fromhex("0004000430303035"))
    client.on_config = MagicMock()
    client.on_config_read_response = MagicMock()
    client.on_config_register_value = MagicMock(return_value=(0, None))
    if stage == "metadata":
        client.on_config.side_effect = error("metadata failed")
    else:
        client.on_config_read_response.side_effect = [error("next read failed"), None]
    msg = SimpleNamespace(topic=f"c/33/{DEVICE}", payload=b"wire", qos=0, retain=False, properties=None)
    try:
        with patch("grobro.grobro.client.parser.unscramble", return_value=packet):
            client._client.on_message(None, None, msg)
        assert [call.args[1:] for call in client.on_config_register_value.call_args_list] == [(4, 5), (5, "1")]
        assert [call.args[1] for call in client.on_config_read_response.call_args_list] == [4, 5]
        assert client.on_config.call_args.args[1].data_interval == "5"
    finally:
        client.stop()


@pytest.mark.parametrize("error", [RuntimeError, OSError])
@pytest.mark.parametrize("target_callback", [False, True])
def test_failed_readback_publication_does_not_drop_compound_responses(tmp_path, monkeypatch, error, target_callback):
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client"):
        client = Client(MQTTConfig(host="localhost", port=1883), MQTTConfig(host="localhost", port=1884))
    client.on_config_read_response = MagicMock()
    publisher = MagicMock(side_effect=[error("temporarily disconnected"), (0, None)])
    if target_callback:
        client.on_config_register_value = publisher
    else:
        client._client.publish = publisher
    msg = SimpleNamespace(topic=f"c/33/{DEVICE}", payload=b"wire", qos=0, retain=False, properties=None)
    try:
        with patch("grobro.grobro.client.parser.unscramble", return_value=PACKET):
            client._client.on_message(None, None, msg)
        assert publisher.call_count == 2
        assert [call.args[1] for call in client.on_config_read_response.call_args_list] == [76, 5]
        if target_callback:
            assert publisher.call_args_list[1].args == (DEVICE, 5, "1")
        else:
            assert publisher.call_args_list[1].args == (f"homeassistant/config/grobro/{DEVICE}/5/get", "1")
    finally:
        client.stop()
