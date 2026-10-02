import builtins
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from grobro.ha import battery_position as bp


@pytest.mark.parametrize("error", [PermissionError, OSError])
@pytest.mark.parametrize("previously_loaded", [False, True])
def test_transient_manual_read_failure_does_not_cache_empty_assignments(tmp_path, monkeypatch, error, previously_loaded):
    monkeypatch.chdir(tmp_path)
    path = Path("battery_manual_positions.json")
    path.write_text(json.dumps({"0PVPTEST": {"2": "BATTERY00000001"}}), encoding="utf-8")
    client = SimpleNamespace()
    expected = {"0PVPTEST": {2: "BATTERY00000001", 3: bp.AUTO_ASSIGNMENT, 4: bp.AUTO_ASSIGNMENT}}
    if previously_loaded:
        assert bp._manual_positions(client) == expected
        previous_stat = path.stat()
        path.write_text(json.dumps({"0PVPTEST": {"3": "BATTERY00000001"}}), encoding="utf-8")
        os.utime(path, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns + 1_000_000_000))
    original_open = builtins.open
    def fail_manual(filename, *args, **kwargs):
        if str(filename) == str(path):
            raise error("temporarily unreadable")
        return original_open(filename, *args, **kwargs)
    with patch("builtins.open", side_effect=fail_manual):
        for _ in range(2):
            assert bp._manual_positions(client) == (expected if previously_loaded else {})
    restored = bp._manual_positions(client)
    slot = 3 if previously_loaded else 2
    assert restored["0PVPTEST"][slot] == "BATTERY00000001"
    # A successful read resumes the unchanged-file fast path.
    with patch.object(bp, "_load_manual_positions", side_effect=AssertionError("unnecessary reload")):
        assert bp._manual_positions(client) == restored


def test_deleting_manual_file_intentionally_clears_assignments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = Path("battery_manual_positions.json")
    path.write_text(json.dumps({"0PVPTEST": {"2": "BATTERY00000001"}}), encoding="utf-8")
    client = SimpleNamespace()
    assert bp._manual_positions(client)["0PVPTEST"][2] == "BATTERY00000001"
    path.unlink()
    assert bp._manual_positions(client) == {}


def test_default_loader_keeps_best_effort_contract(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("builtins.open", side_effect=PermissionError("unreadable")):
        assert bp._load_manual_positions() == {}


@pytest.mark.parametrize("error", [PermissionError, OSError])
def test_manual_save_read_failure_preserves_other_devices(tmp_path, monkeypatch, error):
    monkeypatch.chdir(tmp_path)
    path = Path("battery_manual_positions.json")
    path.write_text(json.dumps({"OTHER": {"2": "BATTERY00000001"}}), encoding="utf-8")
    before = path.read_bytes()
    original_open = builtins.open
    def fail_read(filename, mode="r", *args, **kwargs):
        if str(filename) == str(path) and mode == "r":
            raise error("temporarily unreadable")
        return original_open(filename, mode, *args, **kwargs)
    with patch("builtins.open", side_effect=fail_read), pytest.raises(error):
        bp.save_manual_assignments("0PVPTEST", {"3": "BATTERY00000002"})
    assert path.read_bytes() == before
    bp.save_manual_assignments("0PVPTEST", {"3": "BATTERY00000002"})
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["OTHER"]["2"] == "BATTERY00000001"
    assert saved["0PVPTEST"]["3"] == "BATTERY00000002"


@pytest.mark.parametrize("kind", ["automatic", "detected"])
@pytest.mark.parametrize("error", [PermissionError, OSError])
def test_initial_read_failure_never_overwrites_saved_battery_history(tmp_path, monkeypatch, kind, error):
    monkeypatch.chdir(tmp_path)
    filename = "battery_positions.json" if kind == "automatic" else "battery_detected.json"
    path = Path(filename)
    saved = {"OTHER": {"BATTERY00000001": 3}} if kind == "automatic" else {
        "OTHER": [{"physical_slot": 3, "serial": "BATTERY00000001"}],
    }
    path.write_text(json.dumps(saved), encoding="utf-8")
    before = path.read_bytes()
    client = SimpleNamespace()
    original_open = builtins.open
    def fail_read(filename, mode="r", *args, **kwargs):
        if str(filename) == str(path) and mode == "r":
            raise error("temporarily unreadable")
        return original_open(filename, mode, *args, **kwargs)
    def observe():
        if kind == "automatic":
            return bp.stabilize_battery_payload(client, "0PVPTEST", {
                "bat2_ser_part_1": "BATTERY00000002", "bat2_temp": 20,
            })
        bp.observe_battery_serials(client, "0PVPTEST", {"bat2_ser_part_1": "BATTERY00000002"})
    with patch("builtins.open", side_effect=fail_read):
        observe()
        observe()
    assert path.read_bytes() == before
    observe()
    restored = json.loads(path.read_text(encoding="utf-8"))
    assert restored["OTHER"] == saved["OTHER"]
    assert "0PVPTEST" in restored


@pytest.mark.parametrize("manual", [False, True])
def test_unread_automatic_history_recovers_without_changing_manual_choices(tmp_path, monkeypatch, manual):
    monkeypatch.chdir(tmp_path)
    serial = "BATTERY00000001"
    path = Path("battery_positions.json")
    path.write_text(json.dumps({"0PVPTEST": {serial: 3}}), encoding="utf-8")
    before = path.read_bytes()
    if manual:
        bp.save_manual_assignments("0PVPTEST", {"3": serial})
    client = SimpleNamespace()
    payload = {"bat2_ser_part_1": serial, "bat2_temp": 20}
    original_open = builtins.open
    def fail_automatic(filename, mode="r", *args, **kwargs):
        if str(filename) == str(path) and mode == "r":
            raise PermissionError("temporarily unreadable")
        return original_open(filename, mode, *args, **kwargs)
    with patch("builtins.open", side_effect=fail_automatic):
        remapped, _ = bp.stabilize_battery_payload(client, "0PVPTEST", payload)
    assert remapped["bat3_temp" if manual else "bat2_temp"] == 20
    assert path.read_bytes() == before
    remapped, _ = bp.stabilize_battery_payload(client, "0PVPTEST", payload)
    assert remapped["bat3_temp"] == 20
    assert "bat2_temp" not in remapped
    assert path.read_bytes() == before
