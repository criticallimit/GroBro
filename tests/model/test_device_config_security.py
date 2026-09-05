import json
from pathlib import Path

from grobro.model.device_config import DeviceConfig


def test_sensitive_device_config_fields_are_not_persisted(tmp_path: Path):
    path = tmp_path / "config_TEST.json"
    config = DeviceConfig(
        serial_number="TEST",
        password="secret",
        raw="deadbeef",
        sw_version="19.19.14",
    )

    config.to_file(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["serial_number"] == "TEST"
    assert data["sw_version"] == "19.19.14"
    assert "password" not in data
    assert "raw" not in data
