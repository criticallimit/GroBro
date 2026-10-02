from types import SimpleNamespace
from unittest.mock import MagicMock

from grobro.grobro import client as client_module
from grobro.grobro import noah_traffic_debug as traffic


def test_capture_noah_traffic_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(traffic, "REGISTER_DEBUG", True)
    monkeypatch.setattr(traffic, "REGISTER_DEBUG_DIR", str(tmp_path))

    decoded = bytearray(48)
    decoded[6:8] = b"\x01\x05"
    traffic.capture_noah_mqtt_traffic(
        device_id="0PVPTEST",
        direction="device_to_grobro",
        topic="c/33/0PVPTEST",
        payload=b"raw-payload",
        decoded=bytes(decoded),
        qos=1,
        retain=False,
        forwarded_for=None,
    )

    data = (tmp_path / "noah_mqtt_traffic.jsonl").read_text(encoding="utf-8")
    assert '"device_id":"0PVPTEST"' in data
    assert '"direction":"device_to_grobro"' in data
    assert '"payload_len":11' in data


def test_direct_device_and_cloud_paths_capture_noah_traffic(monkeypatch):
    captures = []
    monkeypatch.setattr(client_module, "NOAH_TRAFFIC_CAPTURE_ENABLED", True)
    monkeypatch.setattr(
        client_module,
        "capture_noah_mqtt_traffic",
        lambda **kwargs: captures.append(kwargs),
    )
    monkeypatch.setattr(client_module.parser, "unscramble", lambda payload: b"\x00" * 8)
    monkeypatch.setattr(client_module.parser, "parse_noah_message", lambda payload: None)
    monkeypatch.setattr(
        client_module.GrowattModbusMessage,
        "parse_grobro",
        lambda payload: None,
    )

    instance = object.__new__(client_module.Client)
    device_msg = SimpleNamespace(
        topic="c/33/0PVPTEST",
        payload=b"device",
        qos=1,
        retain=False,
        properties=None,
    )
    cloud_msg = SimpleNamespace(
        topic="s/33/0PVPTEST",
        payload=b"cloud",
        qos=1,
        retain=False,
        properties=None,
    )

    client_module.Client._Client__on_message(instance, None, None, device_msg)
    client_module.Client._Client__on_message_forward_client(
        instance,
        None,
        None,
        cloud_msg,
    )

    assert [entry["direction"] for entry in captures] == [
        "device_to_grobro",
        "cloud_to_grobro",
    ]


def test_direct_publish_path_captures_ha_direction(monkeypatch):
    captures = []
    monkeypatch.setattr(client_module, "NOAH_TRAFFIC_CAPTURE_ENABLED", True)
    monkeypatch.setattr(
        client_module,
        "capture_noah_mqtt_traffic",
        lambda **kwargs: captures.append(kwargs),
    )
    monkeypatch.setattr(client_module.parser, "unscramble", lambda payload: b"decoded")

    mqtt_client = MagicMock()
    mqtt_client.publish.return_value = (0, None)

    client_module._publish_checked(
        mqtt_client,
        "s/33/0PVPTEST",
        b"payload",
        properties=client_module.MQTT_PROP_FORWARD_HA,
    )

    assert len(captures) == 1
    assert captures[0]["direction"] == "grobro_to_device_from_ha"


def test_traffic_debug_hook_is_compatibility_noop():
    assert traffic.install_noah_traffic_debug_hook() is None
