"""Recovery regressions exposed by sustained-load and fault injection checks."""
import builtins
import json
from unittest.mock import MagicMock, patch

import pytest

from grobro import grobro, model
from grobro.grobro import diagnostic_io as dio


def test_shutdown_thread_exhaustion_still_disconnects_every_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = model.MQTTConfig(host="localhost", port=1883)
    with patch("paho.mqtt.client.Client"):
        source = grobro.Client(config, config)
    forwards = [MagicMock(), MagicMock()]
    source._forward_clients.update({"one": forwards[0], "two": forwards[1]})
    with patch("threading.Thread.start", side_effect=RuntimeError("threads unavailable")):
        source.stop()
    source._client.disconnect.assert_called_once()
    source._client.loop_stop.assert_called_once()
    for forward in forwards:
        forward.disconnect.assert_called_once()
    assert not source._forward_clients
    assert source._diagnostic_writer._closed


def test_partial_diagnostic_write_does_not_corrupt_next_record(tmp_path, monkeypatch):
    path = str(tmp_path / "capture.jsonl")
    dio._write_lines(path, '{"before":true}\n')
    original_open = builtins.open
    class BrokenHandle:
        def __init__(self, handle):
            self.handle = handle
        def write(self, text):
            self.handle.write(text[:len(text) // 2])
            self.handle.flush()
            raise OSError("disk full during write")
        def close(self):
            self.handle.close()
    def broken_open(name, mode="r", *args, **kwargs):
        handle = original_open(name, mode, *args, **kwargs)
        return BrokenHandle(handle) if str(name) == path and mode == "a" else handle
    with monkeypatch.context() as scoped:
        scoped.setattr(builtins, "open", broken_open)
        with pytest.raises(OSError):
            dio._write_lines(path, '{"failed":true}\n')
    dio._write_lines(path, '{"after":true}\n')
    records = [json.loads(line) for line in (tmp_path / "capture.jsonl").read_text().splitlines()]
    assert records == [{"before": True}, {"after": True}]



@pytest.mark.parametrize("prefix", [b"", b'{"before":true}\n'])
@pytest.mark.parametrize("tail", [b'{"partial":', b"x" * 20000, b'"\xe2\x82'])
def test_diagnostic_restart_repairs_only_incomplete_tail(tmp_path, prefix, tail):
    path = tmp_path / "capture.jsonl"
    path.write_bytes(prefix + tail)
    dio._write_lines(str(path), '{"after":true}\n')
    assert path.read_bytes() == prefix + b'{"after":true}\n'


def test_diagnostic_tail_is_repaired_before_rotation(tmp_path, monkeypatch):
    monkeypatch.setattr(dio, "MAX_FILE_BYTES", 32)
    path = tmp_path / "capture.jsonl"
    complete = b'{"before":true}\n'
    path.write_bytes(complete + b'{"partial":' * 10)
    dio._write_lines(str(path), '{"after":true}\n')
    # Removing the partial tail makes both complete records fit; no archive needed.
    assert path.read_bytes() == complete + b'{"after":true}\n'
    assert not (tmp_path / "capture.jsonl.1").exists()


@pytest.mark.parametrize("failure", ["constructor", "disconnect"])
def test_shutdown_fallback_failure_does_not_skip_primary_client(tmp_path, monkeypatch, failure):
    monkeypatch.chdir(tmp_path)
    cfg = model.MQTTConfig(host="localhost", port=1883)
    with patch("paho.mqtt.client.Client"):
        source = grobro.Client(cfg, cfg)
    first, second = MagicMock(), MagicMock()
    source._forward_clients.update({"one": first, "two": second})
    if failure == "disconnect":
        first.disconnect.side_effect = OSError("closed socket")
    name = "threading.Thread" if failure == "constructor" else "threading.Thread.start"
    with patch(name, side_effect=RuntimeError("threads unavailable")):
        source.stop()
    first.disconnect.assert_called_once()
    second.disconnect.assert_called_once()
    source._client.disconnect.assert_called_once()
    source._client.loop_stop.assert_called_once()



def test_complete_diagnostic_record_without_newline_is_preserved(tmp_path):
    path = tmp_path / "capture.jsonl"
    path.write_bytes(b'{"before":true}\n{"complete":"\xe2\x82\xac"}')
    dio._write_lines(str(path), '{"after":true}\n')
    assert [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] == [
        {"before": True}, {"complete": "€"}, {"after": True},
    ]
