from unittest.mock import patch

from grobro.grobro.configuration import load_bridge_mqtt_configs
from grobro.model import MQTTConfig


def test_load_bridge_mqtt_configs_preserves_prefixes_and_defaults():
    calls = []

    def fake_from_env(*, prefix, defaults):
        calls.append((prefix, defaults))
        if prefix == "SOURCE":
            return MQTTConfig(host="source.local", port=7006)
        if prefix == "TARGET":
            return MQTTConfig(host="target.local", port=1883)
        return MQTTConfig(host="forward.local", port=7006)

    with patch.object(MQTTConfig, "from_env", side_effect=fake_from_env):
        source, target, forward = load_bridge_mqtt_configs()

    assert source.host == "source.local"
    assert target.host == "target.local"
    assert forward.host == "forward.local"

    assert calls[0][0] == "SOURCE"
    assert calls[0][1].host == "localhost"
    assert calls[0][1].port == 1883

    assert calls[1][0] == "TARGET"
    assert calls[1][1] is source

    assert calls[2][0] == "FORWARD"
    assert calls[2][1].host == "mqtt.growatt.com"
    assert calls[2][1].port == 7006
