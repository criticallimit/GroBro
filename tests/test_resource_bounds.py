"""Resource bounds, cloud lifecycle, and diagnostic recovery."""
import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from grobro import grobro, model
from grobro.grobro import diagnostic_io as dio
from grobro.ha.battery_ingress import BatteryIngressHandler, BoundedIngressServer


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = model.MQTTConfig(host="localhost", port=1883)
    with patch("paho.mqtt.client.Client"):
        client = grobro.Client(cfg, cfg)
    yield client
    client.stop()


def test_cloud_initial_connection_is_async_and_reused(source):
    forward = MagicMock()
    forward.connect.side_effect = AssertionError("Blocking connect must not run")
    with patch("paho.mqtt.client.Client", return_value=forward) as factory:
        for _ in range(10):
            source._Client__publish_to_growatt_server("QMNTEST", "c/QMNTEST", b"data", 0, False)
    assert factory.call_count == 1
    forward.connect_async.assert_called_once_with("localhost", 1883, 60)
    forward.reconnect_delay_set.assert_called_once_with(min_delay=1, max_delay=60)
    assert len(source._forward_pending["forward_client_QMNTEST"]) == 10


def test_cloud_concurrent_creation_has_single_loop(source):
    with patch("paho.mqtt.client.Client") as factory:
        with ThreadPoolExecutor(max_workers=4) as pool:
            clients = list(pool.map(source._Client__connect_to_growatt_server, ["QMNTEST"] * 20))
    assert factory.call_count == 1
    assert all(item is clients[0] for item in clients)
    clients[0].loop_start.assert_called_once()


def test_cloud_failed_loop_start_keeps_packet_and_retries(source):
    forward = MagicMock()
    forward.loop_start.side_effect = [RuntimeError("thread unavailable"), None]
    forward.publish.return_value = (0, None)
    with patch("paho.mqtt.client.Client", return_value=forward):
        with pytest.raises(RuntimeError):
            source._Client__publish_to_growatt_server("QMNTEST", "c/QMNTEST", b"one", 0, False)
        assert not source._forward_clients
        source._Client__publish_to_growatt_server("QMNTEST", "c/QMNTEST", b"two", 0, False)
    forward.on_connect(forward, None, None, SimpleNamespace(is_failure=False), None)
    assert [call.kwargs["payload"] for call in forward.publish.call_args_list] == [b"one", b"two"]


def test_cloud_late_connack_after_stop_does_not_reactivate(source):
    with patch("paho.mqtt.client.Client") as factory:
        forward = source._Client__connect_to_growatt_server("QMNTEST")
    source.stop()
    forward.on_connect(forward, None, None, SimpleNamespace(is_failure=False), None)
    forward.subscribe.assert_not_called()
    source._Client__publish_to_growatt_server("QMNTEST", "c/QMNTEST", b"late", 0, False)
    assert not source._forward_pending
    assert not source._forward_clients
    assert source._Client__connect_to_growatt_server("QMNTEST") is None
    assert factory.call_count == 1


def test_cloud_flush_does_not_serialize_unrelated_devices(source):
    entered, release, second = threading.Event(), threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return (0, None)
    for device in ("QMNONE", "QMNTWO"):
        source._Client__queue_growatt_forward(device, "topic", b"data", 0, False)
    worker = threading.Thread(target=source._Client__flush_growatt_forward_queue, args=("QMNONE", SimpleNamespace(publish=slow)))
    worker.start()
    try:
        assert entered.wait(3)
        def fast(*args, **kwargs):
            second.set()
            return (0, None)
        source._Client__flush_growatt_forward_queue("QMNTWO", SimpleNamespace(publish=fast))
        assert second.is_set()
    finally:
        release.set()
        worker.join(3)


def test_gateway_failed_save_retries_without_losing_live_routing(source):
    original = model.DeviceConfig.to_file
    with patch.object(model.DeviceConfig, "to_file", side_effect=OSError("disk full")):
        source._remember_gateway("RAQTEST", "PTQTEST")
    assert source._ptq_for_raq["RAQTEST"] == "PTQTEST"
    assert "RAQTEST" in source._gateway_dirty
    with patch.object(model.DeviceConfig, "to_file", autospec=True, side_effect=original) as save:
        source._remember_gateway("RAQTEST", "PTQTEST")
        source._remember_gateway("RAQTEST", "PTQTEST")
    assert save.call_count == 1
    assert not source._gateway_dirty
    assert model.DeviceConfig.from_file("gateway_RAQTEST.json").serial_number == "PTQTEST"


def test_diagnostic_rotation_preserves_whole_records_and_order(tmp_path, monkeypatch):
    monkeypatch.setattr(dio, "MAX_FILE_BYTES", 20)
    path = tmp_path / "capture.jsonl"
    for index in range(10):
        dio.append_lines(str(path), json.dumps({"n": index}) + "\n")
    assert len(list(tmp_path.iterdir())) == 4
    records = []
    for name in [f"{path}.{index}" for index in (3, 2, 1)] + [str(path)]:
        from pathlib import Path
        file = Path(name)
        assert file.stat().st_size <= 20
        records.extend(json.loads(line)["n"] for line in file.read_text().splitlines())
    assert records == list(range(2, 10))


def test_diagnostic_worker_is_lazy_and_drains_in_order(tmp_path):
    writer = dio.DiagnosticWriter()
    assert writer._thread is None
    path = str(tmp_path / "capture.jsonl")
    for index in range(20):
        assert writer.submit(path, json.dumps({"n": index}) + "\n")
    assert writer.stop(3)
    assert not writer.submit(path, "late\n")
    assert [json.loads(line)["n"] for line in (tmp_path / "capture.jsonl").read_text().splitlines()] == list(range(20))


def test_diagnostic_worker_bounds_slow_storage_and_shutdown(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def slow(*args):
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr(dio, "_write_lines", slow)
    writer = dio.DiagnosticWriter(max_jobs=1, max_bytes=8)
    try:
        assert writer.submit("path", "1111")
        assert entered.wait(3)
        assert writer.submit("path", "2222")
        assert not writer.submit("path", "3")
        assert writer._bytes == 8
        assert not writer.flush(0.01)
        assert not writer.stop(0.01)
    finally:
        release.set()
        assert writer.stop(3)
    assert writer._bytes == 0


def test_diagnostic_worker_recovers_after_write_error(monkeypatch):
    writes = MagicMock(side_effect=[OSError("disk full"), None])
    monkeypatch.setattr(dio, "_write_lines", writes)
    writer = dio.DiagnosticWriter()
    try:
        assert writer.submit("path", "one\n")
        assert writer.flush(3)
        assert writer.submit("path", "two\n")
        assert writer.flush(3)
        assert writes.call_count == 2
    finally:
        writer.stop()


def test_diagnostic_scope_offloads_disk_and_restores_context(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def slow(*args):
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr(dio, "_write_lines", slow)
    client = SimpleNamespace(_diagnostic_writer=dio.DiagnosticWriter())
    @dio.diagnostic_scope
    def callback(instance):
        dio.append_lines("path", "line\n")
    try:
        callback(client)
        assert entered.wait(3)
        assert dio._ACTIVE_WRITER.get() is None
    finally:
        release.set()
        client._diagnostic_writer.stop()


def test_ingress_total_body_deadline_expires_despite_partial_data(monkeypatch):
    handler = object.__new__(BatteryIngressHandler)
    handler.headers = {"Content-Length": "4"}
    handler.connection = MagicMock()
    handler.rfile = MagicMock()
    handler.rfile.read1.return_value = b"{"
    monkeypatch.setattr("grobro.ha.battery_ingress.time.monotonic", MagicMock(side_effect=[0, 1, 31]))
    with patch.object(handler, "_send_json") as response:
        assert handler._read_json_body() is None
    assert response.call_args.args[1] == 408
    assert handler.rfile.read1.call_count == 1


def test_ingress_parallel_limit_rejects_excess_and_releases_slot():
    entered, release = threading.Event(), threading.Event()
    class Handler(BatteryIngressHandler):
        def do_GET(self):
            entered.set()
            assert release.wait(3)
            self._send_json({"ok": True})
    server = BoundedIngressServer(("127.0.0.1", 0), Handler, max_requests=1)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    first = socket.create_connection(server.server_address, timeout=3)
    try:
        first.sendall(b"GET / HTTP/1.0\r\n\r\n")
        assert entered.wait(3)
        with socket.create_connection(server.server_address, timeout=3) as excess:
            excess.sendall(b"GET / HTTP/1.0\r\n\r\n")
            assert b"503" in excess.recv(1024)
        release.set()
        assert b"200" in first.recv(4096)
        # Request completion returns the semaphore token.
        assert server._request_slots.acquire(timeout=3)
        server._request_slots.release()
    finally:
        release.set()
        first.close()
        server.shutdown()
        server.server_close()
        thread.join(3)



def test_cloud_slow_network_stop_has_shared_deadline(source, monkeypatch):
    monkeypatch.setattr("grobro.grobro.client.CLOUD_SHUTDOWN_TIMEOUT", 0.01)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    forward = MagicMock()
    def slow_stop():
        entered.set()
        try:
            assert release.wait(3)
        finally:
            finished.set()
    forward.loop_stop.side_effect = slow_stop
    source._forward_clients["one"] = forward
    try:
        source.stop()
        assert entered.is_set()
        assert not finished.is_set()
        assert not source._forward_clients
        assert not source._forward_pending
        forward.disconnect.assert_called_once()
    finally:
        release.set()
        assert finished.wait(3)



def test_metadata_disk_failure_does_not_block_discovery_or_telemetry(tmp_path, monkeypatch):
    from grobro import ha
    from grobro.model.growatt_registers import HomeAssistantInputRegister
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client"):
        target = ha.Client(model.MQTTConfig(host="localhost", port=1883))
    target._client.publish.return_value = (0, None)
    try:
        state = HomeAssistantInputRegister(device_id="QMNTEST", payload={"output_power": 10})
        with patch.object(model.DeviceConfig, "to_file", side_effect=OSError("disk full")):
            target.publish_input_register(state)
        assert "QMNTEST" in target._dirty_device_configs
        assert target._config_cache["QMNTEST"].serial_number == "QMNTEST"
        assert any(call.args[0].endswith("/state") for call in target._client.publish.call_args_list)
        target.publish_input_register(state)
        assert not target._dirty_device_configs
        assert model.DeviceConfig.from_file("config_QMNTEST.json").serial_number == "QMNTEST"
        with patch.object(model.DeviceConfig, "to_file", side_effect=OSError("disk full")):
            target.set_config("QMNTEST", model.DeviceConfig(sw_version="2.0"))
        assert target._config_cache["QMNTEST"].sw_version == "2.0"
        target.publish_input_register(state)
        assert model.DeviceConfig.from_file("config_QMNTEST.json").sw_version == "2.0"
    finally:
        target.stop()


def test_register_rule_cache_is_bounded_and_checks_identity():
    from grobro.ha import performance
    cache = performance._REGISTER_RULES_CACHE
    previous = cache.copy()
    cache.clear()
    try:
        target = SimpleNamespace(input_registers={})
        # Simulate a stale id entry; a different object must never supply rules.
        cache[id(target)] = (object(), ({"wrong": True}, None, None, None))
        assert performance._register_rules(target) == ({}, frozenset(), frozenset(), False)
        for _ in range(100):
            performance._register_rules(SimpleNamespace(input_registers={}))
        assert len(cache) == performance._REGISTER_RULES_CACHE_LIMIT
    finally:
        cache.clear()
        cache.update(previous)



def test_config_ack_can_arrive_inside_publish(source, caplog):
    device = "0PVP0000TEST0001"
    source._client.publish.return_value = (0, None)
    ack = b"\x00\x01\x00\x07\x00\x00\x01\x18"
    message = SimpleNamespace(topic=f"c/33/{device}", payload=b"wire", properties=None, qos=0, retain=False)
    def publish(*args, **kwargs):
        source._client.on_message(None, None, message)
        return (0, None)
    caplog.set_level("INFO")
    source._client.publish.side_effect = publish
    with patch("grobro.grobro.client.parser.unscramble", return_value=ack), patch("grobro.grobro.client.parser.parse_config_ack", return_value={"device_id": device, "register_no": 465}):
        source.send_config_message(device, 31, "2026-10-02 00:00:00")
    assert not source._pending_config_writes
    assert 'setting accepted for "System Time" (register 31)' in caplog.text


@pytest.mark.parametrize("failure", [4, RuntimeError("publish failed")])
def test_failed_config_publish_rolls_back_pending_reservation(source, failure):
    if isinstance(failure, Exception):
        source._client.publish.side_effect = failure
        with pytest.raises(RuntimeError):
            source.send_config_message("QMNTEST", 31, "2026-10-02 00:00:00")
    else:
        source._client.publish.return_value = (failure, None)
        assert source.send_config_message("QMNTEST", 31, "2026-10-02 00:00:00")[0] == failure
    assert not source._pending_config_writes


def test_ingress_assignment_disk_failure_returns_controlled_error():
    handler = object.__new__(BatteryIngressHandler)
    handler.path = "/api/assignments"
    with patch.object(handler, "_reject_untrusted_client", return_value=False), patch.object(handler, "_read_json_body", return_value={"device_id": "0PVPTEST", "assignments": {}}), patch("grobro.ha.battery_ingress.save_manual_assignments", side_effect=OSError("disk full")), patch.object(handler, "_send_json") as response:
        handler.do_POST()
    assert response.call_args.args[1] == 500



@pytest.mark.parametrize("target", ["threading.Thread", "threading.Thread.start"])
@pytest.mark.parametrize("error", [RuntimeError, OSError])
def test_diagnostic_thread_start_failure_is_retryable(tmp_path, target, error):
    writer = dio.DiagnosticWriter()
    path = str(tmp_path / "capture.jsonl")
    with patch(target, side_effect=error("threads unavailable")):
        assert not writer.submit(path, "discarded\n")
    assert writer._bytes == 0
    assert not writer._queue
    assert writer._thread is None
    assert writer.submit(path, "recovered\n")
    assert writer.stop(3)
    assert (tmp_path / "capture.jsonl").read_text() == "recovered\n"



def test_ingress_headers_have_total_deadline_and_preserve_buffer(monkeypatch):
    from io import BytesIO
    from grobro.ha.battery_ingress import _HeaderDeadlineReader
    connection = MagicMock()
    connection.gettimeout.return_value = 10
    clock = [0]
    monkeypatch.setattr("grobro.ha.battery_ingress.time.monotonic", lambda: clock[0])
    reader = _HeaderDeadlineReader(BytesIO(b"GET / HTTP/1.0\r\nHeader: one\r\n\r\nbody"), connection)
    assert reader.readline(65537) == b"GET / HTTP/1.0\r\n"
    clock[0] = 9
    assert reader.readline(65537) == b"Header: one\r\n"
    clock[0] = 11
    with pytest.raises(TimeoutError):
        reader.readline(65537)
    assert reader.read1(6) == b"\r\nbody"
    assert connection.settimeout.call_args.args == (10,)
