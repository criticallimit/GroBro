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

def test_traffic_debug_hook_is_compatibility_noop():
    assert traffic.install_noah_traffic_debug_hook() is None
