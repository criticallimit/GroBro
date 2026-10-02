"""Persistence recovery and callback interleaving regressions."""
import json
from collections import deque
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from grobro import grobro, ha, model
from grobro.ha import battery_position as bp

SERIAL = {"bat2_ser_part_1": "SN00200000000001"}


def test_detected_batteries_retry_failed_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = SimpleNamespace()
    original = bp._save_json_atomic
    with patch.object(bp, "_save_json_atomic", side_effect=OSError("disk full")):
        bp.observe_battery_serials(client, "0PVPTEST", SERIAL)
    assert not client._battery_detected_serials
    with patch.object(bp, "_save_json_atomic", wraps=original) as save:
        bp.observe_battery_serials(client, "0PVPTEST", SERIAL)
        bp.observe_battery_serials(client, "0PVPTEST", SERIAL)
    assert save.call_count == 1
    assert json.loads((tmp_path / "battery_detected.json").read_text())["0PVPTEST"][0]["physical_slot"] == 2


def test_stable_positions_survive_recovered_write_and_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = SimpleNamespace()
    with patch.object(bp, "_save_all_positions", side_effect=OSError("disk full")):
        first = bp.stabilize_battery_payload(client, "0PVPTEST", SERIAL)
    assert client._battery_positions_dirty
    original = bp._save_all_positions
    with patch.object(bp, "_save_all_positions", wraps=original) as save:
        assert bp.stabilize_battery_payload(client, "0PVPTEST", SERIAL) == first
        bp.stabilize_battery_payload(client, "0PVPTEST", SERIAL)
    assert save.call_count == 1
    assert not client._battery_positions_dirty
    restarted = SimpleNamespace()
    assert bp.stabilize_battery_payload(restarted, "0PVPTEST", SERIAL) == first
    assert restarted._battery_position_maps == client._battery_position_maps


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = model.MQTTConfig(host="localhost", port=1883)
    with patch("paho.mqtt.client.Client"):
        source = grobro.Client(config, config)
        target = ha.Client(config)
    yield source, target
    source.stop()
    target.stop()


@pytest.mark.parametrize("status", [0, 4])
def test_queue_overflow_during_publish_keeps_unsent_successor(clients, status):
    source, _ = clients
    key = "forward_client_0PVPTEST"
    source._forward_pending[key] = deque(("topic", str(i).encode(), 0, False) for i in range(100))
    sent = []
    def publish(topic, payload, **kwargs):
        sent.append(int(payload))
        if len(sent) == 1:
            source._Client__queue_growatt_forward("0PVPTEST", "topic", b"100", 0, False)
            return (status, None)
        return (0, None)
    mqtt = SimpleNamespace(publish=publish)
    source._Client__flush_growatt_forward_queue("0PVPTEST", mqtt)
    if status:
        assert source._forward_pending[key][0][1] == b"1"
        source._Client__flush_growatt_forward_queue("0PVPTEST", mqtt)
    assert sent == list(range(101))


def test_timeout_serializes_offline_with_new_telemetry(clients, monkeypatch):
    _, target = clients
    clock = [0]
    timers = []
    def timer(interval, function, args):
        item = SimpleNamespace(function=function, args=args, start=lambda: None, cancel=lambda: None, is_alive=lambda: True)
        timers.append(item)
        return item
    monkeypatch.setattr("grobro.ha.timer_runtime.daemon_timer", timer)
    monkeypatch.setattr("grobro.ha.client.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("grobro.ha.client.DEVICE_TIMEOUT", 120)
    target._Client__reset_device_timer("QMNTEST")
    clock[0] = 120
    entered, release, started, updated = Event(), Event(), Event(), Event()
    transitions = []
    def availability(device, online):
        transitions.append(online)
        if not online:
            entered.set()
            assert release.wait(3)
    monkeypatch.setattr(target, "_Client__publish_availability", availability)
    def update():
        started.set()
        with target._runtime_lock:
            target._Client__reset_device_timer("QMNTEST")
            target._Client__publish_availability("QMNTEST", True)
            updated.set()
    expired = Thread(target=timers[0].function, args=timers[0].args)
    fresh = Thread(target=update)
    try:
        expired.start()
        assert entered.wait(3)
        fresh.start()
        assert started.wait(3)
        assert not updated.wait(0.05)
    finally:
        release.set()
        expired.join(3)
        if fresh.ident is not None:
            fresh.join(3)
    assert updated.is_set()
    assert transitions == [False, True]
    assert "QMNTEST" in target._device_last_seen


@pytest.mark.parametrize("stable", [False, True])
def test_single_battery_snapshot_preserves_manual_changes(tmp_path, monkeypatch, stable):
    monkeypatch.chdir(tmp_path)
    client = SimpleNamespace()
    with patch.object(bp, "_serials_from_payload", wraps=bp._serials_from_payload) as serials, patch.object(bp, "_manual_positions", wraps=bp._manual_positions) as manual:
        bp.prepare_battery_payload(client, "0PVPTEST", SERIAL, use_stable_auto=stable)
    assert serials.call_count == manual.call_count == 1
    # Manual changes remain visible on the next packet and override automatic slots.
    client._battery_manual_position_maps = {"0PVPTEST": {3: "SN00200000000001"}}
    client._battery_manual_position_mtime = None
    mapped, maximum = bp.prepare_battery_payload(client, "0PVPTEST", SERIAL, use_stable_auto=stable)
    assert mapped["bat3_ser_part_1"] == "SN00200000000001"
    assert maximum == 3


def test_ingress_deep_json_returns_client_error():
    from io import BytesIO
    from grobro.ha.battery_ingress import BatteryIngressHandler
    handler = object.__new__(BatteryIngressHandler)
    body = b"[" * 2000 + b"0" + b"]" * 2000
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = BytesIO(body)
    handler.connection = MagicMock()
    with patch.object(handler, "_send_json") as response:
        assert handler._read_json_body() is None
    assert response.call_args.args[1] == 400



def test_config_snapshot_reduces_reads_and_detects_external_replace(clients):
    from pathlib import Path
    from grobro.ha.config_runtime import load_persisted_config
    _, target = clients
    path = "config_QMNTEST.json"
    model.DeviceConfig(serial_number="QMNTEST", sw_version="1").to_file(path)
    original = model.DeviceConfig.from_file
    with patch.object(model.DeviceConfig, "from_file", wraps=original) as read:
        for _ in range(100):
            assert load_persisted_config(target, path).sw_version == "1"
        assert read.call_count == 1
        model.DeviceConfig(serial_number="QMNTEST", sw_version="2").to_file(path)
        assert load_persisted_config(target, path).sw_version == "2"
        assert read.call_count == 2
        Path(path).unlink()
        assert load_persisted_config(target, path) is None
        model.DeviceConfig(serial_number="QMNTEST", sw_version="3").to_file(path)
        assert load_persisted_config(target, path).sw_version == "3"



def test_ingress_incomplete_body_times_out_and_restores_socket_timeout():
    from grobro.ha.battery_ingress import BatteryIngressHandler
    handler = object.__new__(BatteryIngressHandler)
    handler.headers = {"Content-Length": "20"}
    handler.connection = MagicMock()
    handler.connection.gettimeout.return_value = None
    handler.rfile = MagicMock()
    handler.rfile.read1.side_effect = TimeoutError()
    with patch.object(handler, "_send_json") as response:
        assert handler._read_json_body() is None
    assert response.call_args.args[1] == 408
    assert handler.close_connection
    assert handler.connection.settimeout.call_args_list[0].args == (30,)
    assert handler.connection.settimeout.call_args_list[-1].args == (None,)


@pytest.mark.parametrize("replace", ["restart", "reschedule"])
def test_cancelled_device_timer_cannot_replace_current_timer(clients, monkeypatch, replace):
    from grobro.ha.timer_runtime import cancel_runtime_timers

    _, target = clients
    clock = [0.0]
    timers = []
    def timer(interval, function, args):
        item = SimpleNamespace(function=function, args=args, start=lambda: None,
                               cancel=lambda: None, is_alive=lambda: True)
        timers.append(item)
        return item
    monkeypatch.setattr("grobro.ha.timer_runtime.daemon_timer", timer)
    monkeypatch.setattr("grobro.ha.client.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("grobro.ha.client.DEVICE_TIMEOUT", 120)
    availability = MagicMock()
    monkeypatch.setattr(target, "_Client__publish_availability", availability)
    target._Client__reset_device_timer("QMNTEST")
    old = timers[0]
    clock[0] = 60.0
    if replace == "restart":
        cancel_runtime_timers(target)
        target._Client__reset_device_timer("QMNTEST")
    else:
        target._Client__reset_device_timer("QMNTEST")
        clock[0] = 120.0
        old.function(*old.args)
    current = target._device_timers["QMNTEST"]
    count = len(timers)
    old.function(*old.args)
    assert len(timers) == count
    assert target._device_timers["QMNTEST"] is current
    availability.assert_not_called()
    clock[0] = 180.0
    current.function(*current.args)
    availability.assert_called_once_with("QMNTEST", False)
    assert "QMNTEST" not in target._device_timers
