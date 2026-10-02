"""Cross-area regressions identified by the complete repository review."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from grobro.ha import localization
from grobro.model.modbus_function import (
    GrowattModbusFunctionMultiple,
    GrowattModbusFunctionSingle,
)
from grobro.model.modbus_message import (
    GrowattMetadata,
    GrowattModbusFunction,
    GrowattModbusMessage,
)
from datetime import datetime
from grobro.grobro import client as source
from grobro.model.mqtt_config import MQTTConfig


@pytest.mark.parametrize("dump_dir", ["", "blocked"])
def test_optional_dump_cannot_prevent_module_import(tmp_path, dump_dir):
    if dump_dir:
        (tmp_path / dump_dir).write_text("not a directory", encoding="utf-8")
        dump_dir += "/capture"
    environment = dict(os.environ, DUMP_MESSAGES="true", DUMP_DIR=dump_dir)
    environment["PYTHONPATH"] = str(Path.cwd())
    result = subprocess.run(
        [sys.executable, "-c", "import grobro.grobro.client"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_temporary_language_failure_preserves_names_and_recovers(monkeypatch):
    monkeypatch.setattr(localization, "_LANGUAGE_CACHE", {"value": "de", "checked_at": 100.0})
    monkeypatch.setattr(localization.time, "monotonic", lambda: 161.0)
    defaults = []

    def unavailable(default):
        defaults.append(default)
        return default

    monkeypatch.setattr(localization, "get_home_assistant_language", unavailable)
    assert localization.runtime_language() == "de"
    assert defaults == ["de"]
    monkeypatch.setattr(localization.time, "monotonic", lambda: 222.0)
    monkeypatch.setattr(localization, "get_home_assistant_language", lambda default: "fr")
    assert localization.runtime_language() == "fr"


def test_real_write_ack_roundtrip_preserves_body():
    packet = bytes.fromhex(
        "0001000700250106"
        "3050565035305a5231373554303045380000000000000000000000000000"
        "01010000d00d1c"
    )
    parsed = GrowattModbusMessage.parse_grobro(packet)
    assert parsed is not None
    assert parsed.build_grobro() == packet[:-2]
    rebuilt = GrowattModbusMessage.parse_grobro(parsed.build_grobro() + packet[-2:])
    assert rebuilt == parsed


@pytest.mark.parametrize("kind", ["single", "multiple", "message", "metadata"])
def test_oversized_device_serial_is_not_silently_truncated(kind):
    serial = "QMN" + "X" * 28
    models = {
        "single": GrowattModbusFunctionSingle(
            device_id=serial, function=GrowattModbusFunction.READ_SINGLE_REGISTER,
            register=0, value=0,
        ),
        "multiple": GrowattModbusFunctionMultiple(
            device_id=serial, function=GrowattModbusFunction.PRESET_MULTIPLE_REGISTER,
            start=0, end=0, values=b"\x00\x01",
        ),
        "message": GrowattModbusMessage(
            unknown=1, device_id=serial, function=GrowattModbusFunction.READ_HOLDING_REGISTER,
            register_blocks=[],
        ),
        "metadata": GrowattMetadata(device_sn=serial, timestamp=datetime(2026, 1, 1)),
    }
    with pytest.raises(ValueError, match="30"):
        models[kind].build_grobro()


def test_release_publishes_only_after_image_and_recovers_missing_image():
    workflow = Path(".github/workflows/publish-release.yml").read_text(encoding="utf-8")
    assert workflow.index("- name: Build and publish release image") < workflow.index("- name: Publish GitHub release")
    assert "imagetools inspect" in workflow
    build = workflow.split("- name: Build and publish release image", 1)[1].split("- name:", 1)[0]
    assert "steps.image_check.outputs.exists" in build
    recovery = workflow.index("- name: Restore published release source for image recovery")
    assert recovery < workflow.index("- name: Build and publish release image")
    assert "ref: refs/tags/${{ steps.version.outputs.tag }}" in workflow[recovery:]


def test_prerelease_image_does_not_replace_latest():
    workflow = Path(".github/workflows/docker-build.yml").read_text(encoding="utf-8")
    assert "PRERELEASE: ${{ github.event.release.prerelease }}" in workflow
    assert 'if [[ "$PRERELEASE" != "true" ]]' in workflow


def test_missing_config_acks_have_bounded_tracking_without_false_matching(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    mqtt_client = MagicMock()
    mqtt_client.publish.return_value = (0, None)
    monkeypatch.setattr(source.mqtt, "Client", lambda **kwargs: mqtt_client)
    monkeypatch.setattr(source, "MAX_PENDING_CONFIG_WRITES", 3, raising=False)
    config = MQTTConfig(host="localhost", port=1883)
    client = source.Client(config, config)
    device_id = "0PVP0000TEST0001"
    for _ in range(20):
        client.send_config_message(device_id, 31, "2026-10-02 00:00:00")
    assert mqtt_client.publish.call_count == 20
    assert len(client._pending_config_writes.get(device_id, ())) <= 3
    assert device_id in client._config_ack_tracking_disabled
    monkeypatch.setattr(source.parser, "unscramble", lambda payload: b"\x00\x01\x00\x07\x00\x00\x01\x18")
    monkeypatch.setattr(source.parser, "parse_config_ack", lambda payload: {"device_id": device_id, "register_no": 465})
    caplog.set_level("INFO", logger=source.LOG.name)
    mqtt_client.on_message(None, None, SimpleNamespace(
        topic=f"c/33/{device_id}", payload=b"wire", qos=0, retain=False, properties=None,
    ))
    assert '"Unknown setting" (register 465)' in caplog.text
    assert '"System Time" (register 31)' not in caplog.text
    client.stop()
    assert not client._config_ack_tracking_disabled
