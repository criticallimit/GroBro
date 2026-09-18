from types import SimpleNamespace

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


def test_traffic_hook_wraps_device_cloud_and_publish_paths(monkeypatch):
    captures = []

    monkeypatch.setattr(traffic, "REGISTER_DEBUG", True)
    monkeypatch.setattr(traffic, "_INSTALLED", False)
    monkeypatch.setattr(
        traffic,
        "capture_noah_mqtt_traffic",
        lambda **kwargs: captures.append(kwargs),
    )
    monkeypatch.setattr(traffic, "_safe_unscramble", lambda payload: b"decoded")
    monkeypatch.setattr(client_module, "get_property", lambda msg, prop: None)

    monkeypatch.setattr(
        client_module.Client,
        "_Client__on_message",
        lambda self, client, userdata, msg: "device-result",
    )
    monkeypatch.setattr(
        client_module.Client,
        "_Client__on_message_forward_client",
        lambda self, client, userdata, msg: "cloud-result",
    )
    monkeypatch.setattr(
        client_module,
        "_publish_checked",
        lambda client, topic, payload=None, **kwargs: "publish-result",
    )

    traffic.install_noah_traffic_debug_hook()

    instance = object.__new__(client_module.Client)
    msg = SimpleNamespace(
        topic="c/33/0PVPTEST",
        payload=b"payload",
        qos=1,
        retain=False,
    )

    assert client_module.Client._Client__on_message(
        instance, None, None, msg
    ) == "device-result"
    assert client_module.Client._Client__on_message_forward_client(
        instance, None, None, msg
    ) == "cloud-result"
    assert client_module._publish_checked(
        None,
        "s/33/0PVPTEST",
        b"payload",
        properties=client_module.MQTT_PROP_FORWARD_HA,
    ) == "publish-result"

    assert [entry["direction"] for entry in captures] == [
        "device_to_grobro",
        "cloud_to_grobro",
        "grobro_to_device_from_ha",
    ]

    # Idempotency: a second install must not add another wrapper layer.
    wrapped = client_module.Client._Client__on_message
    traffic.install_noah_traffic_debug_hook()
    assert client_module.Client._Client__on_message is wrapped
