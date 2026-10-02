"""Regression coverage for persistence and Supervisor boundary failures."""
import json
import os
from http.client import IncompleteRead
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from grobro.ha import battery_position as bp
from grobro.ha import supervisor_config as sc


@pytest.mark.parametrize("slot", [float("inf"), float("-inf"), 1e300])
@pytest.mark.parametrize("kind", ["automatic", "detected"])
def test_invalid_numeric_slots_preserve_other_valid_entries(tmp_path, kind, slot):
    path = tmp_path / "positions.json"
    if kind == "automatic":
        raw = {"0PVPTEST": {"SN00200000000001": slot, "SN00300000000002": 3}}
        expected = {"0PVPTEST": {"SN00300000000002": 3}}
        load = bp._load_all_positions
    else:
        raw = {"0PVPTEST": [{"serial": "SN00200000000001", "physical_slot": slot},
                            {"serial": "SN00300000000002", "physical_slot": 3}]}
        expected = {"0PVPTEST": [{"serial": "SN00300000000002", "physical_slot": 3}]}
        load = bp._load_detected_serials
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load(str(path)) == expected


def test_manual_cache_detects_atomic_replace_with_same_mtime(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "battery_manual_positions.json"
    client = SimpleNamespace()
    bp.save_manual_assignments("0PVPTEST", {"2": "SN00200000000001"})
    before = path.stat()
    assert bp._manual_positions(client)["0PVPTEST"][2] == "SN00200000000001"
    replacement = tmp_path / "replacement.json"
    updated = json.loads(path.read_text(encoding="utf-8"))
    updated["0PVPTEST"]["2"], updated["0PVPTEST"]["3"] = updated["0PVPTEST"]["3"], updated["0PVPTEST"]["2"]
    replacement.write_text(json.dumps(updated, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    assert replacement.stat().st_size == before.st_size
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, path)
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert bp._manual_positions(client)["0PVPTEST"][3] == "SN00200000000001"
    assert bp._manual_positions(client)["0PVPTEST"][2] == bp.AUTO_ASSIGNMENT


def test_manual_cache_does_not_reread_unchanged_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bp.save_manual_assignments("0PVPTEST", {"2": "SN00200000000001"})
    client = SimpleNamespace()
    with patch.object(bp, "_load_manual_positions", wraps=bp._load_manual_positions) as load:
        for _ in range(20):
            assert bp._manual_positions(client)["0PVPTEST"][2] == "SN00200000000001"
    assert load.call_count == 1


@pytest.mark.parametrize("raw", [b'{"result":[],"data":{}}', b'{"result":{},"data":{}}',
                                  b"[" * 20000 + b"0" + b"]" * 20000], ids=["list-result", "dict-result", "deep-json"])
def test_invalid_supervisor_response_is_reported_as_api_error(monkeypatch, raw):
    monkeypatch.setattr(sc, "_token", lambda: "test-token")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = raw
    with patch.object(sc.urllib.request, "urlopen", return_value=response):
        with pytest.raises(sc.SupervisorConfigError):
            sc._supervisor_request("GET", "/addons/self/info")


@pytest.mark.parametrize("text", [False, True])
def test_interrupted_supervisor_response_is_reported_as_api_error(monkeypatch, text):
    monkeypatch.setattr(sc, "_token", lambda: "test-token")
    response = MagicMock()
    response.__enter__.return_value.read.side_effect = IncompleteRead(b"partial", 20)
    with patch.object(sc.urllib.request, "urlopen", return_value=response):
        with pytest.raises(sc.SupervisorConfigError):
            if text:
                sc._supervisor_text_request("/addons/self/logs")
            else:
                sc._supervisor_request("GET", "/addons/self/info")


@pytest.mark.parametrize("failure", ["construct", "start"])
@pytest.mark.parametrize("error", [RuntimeError, OSError])
def test_restart_still_reaches_supervisor_when_worker_cannot_start(monkeypatch, failure, error):
    monkeypatch.setattr(sc.time, "sleep", lambda delay: None)
    request = MagicMock()
    monkeypatch.setattr(sc, "_supervisor_request", request)
    target = "threading.Thread" if failure == "construct" else "threading.Thread.start"
    with patch(target, side_effect=error("threads unavailable")):
        sc.schedule_restart()
    request.assert_called_once_with("POST", "/addons/self/restart", {})


@pytest.mark.parametrize("timeout", ["invalid", {}, float("inf"), float("nan")])
def test_invalid_restored_timeout_uses_existing_default(monkeypatch, timeout):
    def request(method, path, payload=None):
        return {"options": {"DEVICE_TIMEOUT": timeout}} if path == "/addons/self/info" else {}
    monkeypatch.setattr(sc, "_supervisor_request", request)
    assert sc.get_addon_options()["options"]["DEVICE_TIMEOUT"] == 120


@pytest.mark.parametrize("error", [RuntimeError, OSError])
def test_device_offline_failure_does_not_skip_remaining_shutdown(tmp_path, monkeypatch, error):
    from grobro import ha, model
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client"):
        target = ha.Client(model.MQTTConfig(host="localhost", port=1883))
    target._config_cache = {"QMNTEST1": None, "QMNTEST2": None}
    def publish(topic, *args, **kwargs):
        if topic.endswith("QMNTEST1/availability"):
            raise error("socket unavailable")
        return (0, None)
    target._client.publish.side_effect = publish
    target.stop()
    topics = [call.args[0] for call in target._client.publish.call_args_list]
    assert "homeassistant/grobro/QMNTEST2/availability" in topics
    assert target._bridge_topic() in topics
    target._client.disconnect.assert_called_once()
    target._client.loop_stop.assert_called_once()
    assert target._stopped


@pytest.mark.parametrize("raw, expected", [
    (b'{"result":"ok","data":{"language":"de"}}', {"language": "de"}),
    (b'{"language":"de"}', {"language": "de"}),
    (b"", None),
])
def test_supervisor_response_formats_remain_compatible(monkeypatch, raw, expected):
    monkeypatch.setattr(sc, "_token", lambda: "test-token")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = raw
    with patch.object(sc.urllib.request, "urlopen", return_value=response):
        assert sc._supervisor_request("GET", "/homeassistant/api/config") == expected


def test_supervisor_reported_error_preserves_message(monkeypatch):
    monkeypatch.setattr(sc, "_token", lambda: "test-token")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"result":"error","message":"not available"}'
    with patch.object(sc.urllib.request, "urlopen", return_value=response):
        with pytest.raises(sc.SupervisorConfigError, match="not available"):
            sc._supervisor_request("GET", "/addons/self/info")
