"""Verify telemetry preparation and legacy migration preserve their outputs."""
import json
from unittest.mock import patch

import pytest

from grobro import ha, model
from grobro.ha.firmware_runtime import _firmware_part_names_for_device
from grobro.model.growatt_registers import HomeAssistantInputRegister


@pytest.mark.parametrize("device", ["0PVPTEST00000001", "0HVRTEST00000001"])
def test_firmware_telemetry_keeps_source_and_skips_unchanged_publish(tmp_path, monkeypatch, device):
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client"):
        target = ha.Client(model.MQTTConfig(host="localhost", port=1883))
    target._config_cache[device] = model.DeviceConfig(sw_version="4.0.1.9")
    names = _firmware_part_names_for_device(device)
    values = {name: str(index + 10) for index, name in enumerate(names)}
    source = HomeAssistantInputRegister(device_id=device, payload=values)
    before = source.payload.copy()
    target._client.publish.return_value = (0, None)
    try:
        with patch.object(target, "_Client__publish_device_discovery"), patch.object(
            target, "_Client__refresh_device_activity"
        ):
            target.publish_input_register(source)
            state_calls = [call for call in target._client.publish.call_args_list
                           if call.args[0].endswith("/state")]
            assert len(state_calls) == 1
            published = json.loads(state_calls[0].args[1])
            assert published["fw_version"] == ".".join(values.values()) + ".4019"
            assert source.payload == before
            target._client.publish.reset_mock()
            target.publish_input_register(source)
            assert not target._client.publish.called
    finally:
        target.stop()


def test_legacy_migration_keeps_payload_and_retries_rejected_publication(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client"):
        target = ha.Client(model.MQTTConfig(host="localhost", port=1883))
    device = "QMNTEST"
    registers = model.get_known_registers(device)
    try:
        with patch.object(target, "_publish_discovery_message", return_value=(4, None)) as publish:
            target._Client__migrate_entity_discovery(device, registers)
            first = publish.call_args_list.copy()
            assert len(first) == 1 + 2 * len(registers.holding_registers) + len(registers.input_registers)
            assert all(call.args[1] == '{"migrate_discovery": true}' for call in first)
            assert device not in target._migration_done
            publish.reset_mock()
            publish.return_value = (0, None)
            target._Client__migrate_entity_discovery(device, registers)
            assert publish.call_args_list == first
            publish.reset_mock()
            target._Client__migrate_entity_discovery(device, registers)
            publish.assert_not_called()
    finally:
        target.stop()
