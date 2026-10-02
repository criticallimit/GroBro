"""Read-All publish failures and binary protocol equivalence checks."""
import struct
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from grobro import ha, model
from grobro.grobro import parser


@pytest.mark.parametrize("result", [(4, None), (15, None), SimpleNamespace(rc=4)],
                         ids=["no-connection", "queue-full", "paho-result"])
def test_rejected_read_all_publish_releases_sequence_and_allows_retry(tmp_path, monkeypatch, result):
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client"):
        target = ha.Client(model.MQTTConfig(host="localhost", port=1883))
    device = "QMNTEST"
    target.on_config_read = MagicMock(return_value=result)
    target._read_all_active.add(device)
    target._config_read_queues[device] = deque([4, 5])
    try:
        with patch("grobro.ha.client.Timer"):
            target._Client__kickoff_next_config_read(device)
            assert device not in target._config_read_inflight
            assert device not in target._config_read_queues
            assert device not in target._config_read_timers
            assert device not in target._read_all_active
            target.on_config_read.assert_called_once_with(device, 4)
            target.on_config_read.reset_mock(return_value=True)
            target.on_config_read.return_value = (0, None)
            target._read_all_active.add(device)
            target._config_read_queues[device] = deque([4, 5])
            target._Client__kickoff_next_config_read(device)
            assert target._config_read_inflight[device] == 4
            assert list(target._config_read_queues[device]) == [5]
            target.on_config_read.assert_called_once_with(device, 4)
    finally:
        target.stop()


@pytest.mark.parametrize("result", [None, (0, None), SimpleNamespace(rc=0)])
def test_accepted_read_all_publish_still_waits_for_response(tmp_path, monkeypatch, result):
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client"):
        target = ha.Client(model.MQTTConfig(host="localhost", port=1883))
    target.on_config_read = MagicMock(return_value=result)
    target._read_all_active.add("QMNTEST")
    target._config_read_queues["QMNTEST"] = deque([4, 5])
    try:
        with patch("grobro.ha.client.Timer"):
            target._Client__kickoff_next_config_read("QMNTEST")
        assert target._config_read_inflight["QMNTEST"] == 4
        assert list(target._config_read_queues["QMNTEST"]) == [5]
        assert "QMNTEST" in target._read_all_active
        assert "QMNTEST" in target._config_read_timers
    finally:
        target.stop()


@pytest.mark.parametrize("count", [0, 1, 255])
@pytest.mark.parametrize("odd_tail", [False, True])
def test_noah_0103_preserves_words_and_ignores_incomplete_final_word(count, odd_tail):
    values = [(index * 257) % 65536 for index in range(count)]
    packet = b"\x00" * 38 + b"BZP4N991ML".ljust(16, b"\x00")
    packet += b"".join(struct.pack(">H", value) for value in values)
    if odd_tail:
        packet += b"\xff"
    result = parser.parse_noah_0103(packet)
    assert result == {"message_type": 0x0103, "device_id": "BZP4N991ML",
                      "registers": values, "register_count": count}
