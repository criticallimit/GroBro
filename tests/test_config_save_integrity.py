"""Protect unrelated settings across malformed responses and concurrent saves."""
import json
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from grobro.ha import battery_ingress, supervisor_config as config


@pytest.mark.parametrize("info", [None, {}, [], {"options": None}, {"options": []}, {"options": "bad"}])
@pytest.mark.parametrize("operation", ["read", "save"])
def test_invalid_current_options_never_become_defaults_or_partial_overwrite(monkeypatch, info, operation):
    request = MagicMock(return_value=info)
    monkeypatch.setattr(config, "_supervisor_request", request)
    with pytest.raises(config.SupervisorConfigError):
        if operation == "read":
            config.get_addon_options()
        else:
            config.save_addon_options({"TARGET_MQTT_PORT": 1884})
    request.assert_called_once_with("GET", "/addons/self/info")


def test_parallel_partial_saves_preserve_both_changes_and_unknown_options(monkeypatch):
    stored = {"SOURCE_MQTT_HOST": "old", "TARGET_MQTT_PORT": 1883, "FUTURE": "keep"}
    first_read, second_read, release, second_started = (threading.Event() for _ in range(4))

    def request(method, path, payload=None):
        if method == "GET":
            snapshot = stored.copy()
            if threading.current_thread().name.endswith("_0"):
                first_read.set()
                assert release.wait(3)
            else:
                second_read.set()
            return {"options": snapshot}
        stored.clear()
        stored.update(payload["options"])

    def second_save():
        second_started.set()
        return config.save_addon_options({"TARGET_MQTT_PORT": 1884})

    monkeypatch.setattr(config, "_supervisor_request", request)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="save-test") as pool:
        first = pool.submit(config.save_addon_options, {"SOURCE_MQTT_HOST": "new"})
        try:
            assert first_read.wait(3)
            second = pool.submit(second_save)
            assert second_started.wait(3)
            second_read.wait(0.1)
        finally:
            release.set()
        first.result(timeout=3)
        second.result(timeout=3)
    assert stored == {"SOURCE_MQTT_HOST": "new", "TARGET_MQTT_PORT": 1884, "FUTURE": "keep"}


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js for the actual browser function")
def test_browser_sends_only_edited_settings_and_requires_loaded_baseline():
    html = battery_ingress._INDEX_HTML
    functions = []
    for name in ("collectConfig", "collectConfigChanges"):
        start = html.index(f"function {name}(){{")
        end = html.index("\n}", start) + 2
        functions.append(html[start:end])
    script = """
const assert=require('node:assert/strict');
const CONFIG_KEYS=['SOURCE_MQTT_HOST','TARGET_MQTT_PORT','REGISTER_DEBUG','SOURCE_MQTT_PASS'];
const BOOL_KEYS=new Set(['REGISTER_DEBUG']),INT_KEYS=new Set(['TARGET_MQTT_PORT']);
const fields={SOURCE_MQTT_HOST:{value:'broker'},TARGET_MQTT_PORT:{value:'1883'},REGISTER_DEBUG:{checked:false},SOURCE_MQTT_PASS:{value:'old'}};
const document={getElementById:id=>fields[id.slice(4)]};
let configBaseline=null;
""" + "\n".join(functions) + """
assert.throws(collectConfigChanges);
configBaseline=collectConfig();
assert.deepEqual(collectConfigChanges(),{});
fields.TARGET_MQTT_PORT.value='1884';fields.REGISTER_DEBUG.checked=true;fields.SOURCE_MQTT_PASS.value=' secret ';
const changes=collectConfigChanges();
assert.deepEqual(changes,{TARGET_MQTT_PORT:1884,REGISTER_DEBUG:true,SOURCE_MQTT_PASS:' secret '});
assert.equal(configBaseline.TARGET_MQTT_PORT,1883);
assert.equal(changes.SOURCE_MQTT_HOST,undefined);
console.log(JSON.stringify(changes));
"""
    result = subprocess.run([shutil.which("node"), "-e", script], check=True, capture_output=True, text=True, timeout=5)
    assert json.loads(result.stdout)["SOURCE_MQTT_PASS"] == " secret "
