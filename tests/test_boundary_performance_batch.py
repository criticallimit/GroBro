"""Boundary regressions for buffered ingress and discovery rewriting."""
import json
from io import BufferedReader, BytesIO
from unittest.mock import MagicMock

import pytest

from grobro.ha.battery_ingress import _HeaderDeadlineReader
from grobro.ha.firmware_runtime import _rewrite_firmware_discovery


@pytest.mark.parametrize("buffer_size", [4, 16, 8192])
def test_buffered_headers_preserve_line_limits_and_body(buffer_size):
    raw = b"GET / HTTP/1.0\r\nHeader: " + b"x" * 20000 + b"\r\n\r\n{\"body\":true}"
    stream = BufferedReader(BytesIO(raw), buffer_size=buffer_size)
    connection = MagicMock()
    connection.gettimeout.return_value = 10
    reader = _HeaderDeadlineReader(stream, connection)
    assert reader.readline(5) == b"GET /"
    assert reader.readline(65537) == b" HTTP/1.0\r\n"
    assert reader.readline(65537) == b"Header: " + b"x" * 20000 + b"\r\n"
    assert reader.readline(65537) == b"\r\n"
    body = bytearray()
    while chunk := reader.read1(8192):
        body.extend(chunk)
    assert body == b'{"body":true}'
    assert connection.settimeout.call_args.args == (10,)


def test_buffered_header_deadline_applies_across_lines(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("grobro.ha.battery_ingress.time.monotonic", lambda: clock[0])
    stream = BufferedReader(BytesIO(b"GET / HTTP/1.0\r\nHeader: one\r\n\r\nbody"))
    connection = MagicMock()
    connection.gettimeout.return_value = 10
    reader = _HeaderDeadlineReader(stream, connection)
    assert reader.readline(65537) == b"GET / HTTP/1.0\r\n"
    clock[0] = 11
    with pytest.raises(TimeoutError):
        reader.readline(65537)
    assert reader.read1(100) == b"Header: one\r\n\r\nbody"
    assert connection.settimeout.call_args.args == (10,)


@pytest.mark.parametrize("payload", ["[]", "null", "true", "42", '"text"',
                                     "[" * 20000 + "0" + "]" * 20000],
                         ids=["list", "null", "bool", "number", "text", "deep-json"])
def test_invalid_firmware_discovery_input_is_preserved(payload):
    assert _rewrite_firmware_discovery("0PVPTEST", payload, "19.19.14.4019") == payload


@pytest.mark.parametrize("kind", [str, bytes, bytearray])
def test_firmware_discovery_string_api_preserves_existing_output(kind):
    data = {"dev": {"sw_version": "old"}, "cmps": {"grobro_0PVPTEST_fw_version": {"platform": "sensor"}}}
    raw = json.dumps(data)
    payload = raw if kind is str else kind(raw.encode())
    result = _rewrite_firmware_discovery("0PVPTEST", payload, "19.19.14.4019")
    data["dev"]["sw_version"] = "19.19.14.4019"
    data["cmps"]["grobro_0PVPTEST_fw_version"]["value_template"] = "{{ value_json['fw_version'] }}"
    assert result == json.dumps(data, sort_keys=True, separators=(",", ":"))


def test_buffered_header_deadline_stops_real_trickle_stream():
    import socket
    import threading
    import time

    receiver, sender = socket.socketpair()
    receiver.settimeout(2)
    stopped = threading.Event()
    def trickle():
        try:
            while not stopped.is_set():
                sender.sendall(b"x")
                stopped.wait(0.01)
        except OSError:
            pass
    worker = threading.Thread(target=trickle, daemon=True)
    stream = receiver.makefile("rb")
    try:
        reader = _HeaderDeadlineReader(stream, receiver, timeout=0.05)
        worker.start()
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            reader.readline(65537)
        assert time.monotonic() - started < 1
        assert receiver.gettimeout() == 2
    finally:
        stopped.set()
        stream.close()
        receiver.close()
        sender.close()
        if worker.ident is not None:
            worker.join(1)
