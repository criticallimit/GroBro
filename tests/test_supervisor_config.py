import pytest

from grobro.ha import supervisor_config


def test_normalize_options_validates_types_and_ranges():
    result = supervisor_config.normalize_options(
        {
            "SOURCE_MQTT_PORT": "7006",
            "TARGET_MQTT_TLS": True,
            "MAX_SLOTS": 9,
            "MAX_BAT": "4",
            "LOG_LEVEL": "debug",
            "UNKNOWN": "ignored",
        }
    )

    assert result == {
        "SOURCE_MQTT_PORT": 7006,
        "TARGET_MQTT_TLS": True,
        "MAX_SLOTS": 9,
        "MAX_BAT": "4",
        "LOG_LEVEL": "DEBUG",
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("SOURCE_MQTT_PORT", 70000),
        ("MAX_SLOTS", 10),
        ("MAX_BAT", "5"),
        ("DEVICE_TIMEOUT", -1),
        ("LOG_LEVEL", "TRACE"),
    ],
)
def test_normalize_options_rejects_invalid_values(key, value):
    with pytest.raises(supervisor_config.SupervisorConfigError):
        supervisor_config.normalize_options({key: value})


def test_get_addon_options_merges_defaults(monkeypatch):
    def fake_request(method, path, payload=None):
        if path == "/addons/self/info":
            return {
                "version": "3.1.28",
                "state": "started",
                "options": {"SOURCE_MQTT_HOST": "growatt.local"},
            }
        if path == "/homeassistant/api/config":
            return {"language": "de"}
        raise AssertionError(path)

    monkeypatch.setattr(
        supervisor_config,
        "_supervisor_request",
        fake_request,
    )

    result = supervisor_config.get_addon_options()

    assert result["version"] == "3.1.28"
    assert result["state"] == "started"
    assert result["options"]["SOURCE_MQTT_HOST"] == "growatt.local"
    assert result["options"]["TARGET_MQTT_PORT"] == 1883
    assert result["options"]["REGISTER_DEBUG"] is False
    assert result["language"] == "de"


def test_save_addon_options_preserves_future_unknown_but_drops_retired(monkeypatch):
    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        if path == "/addons/self/info":
            return {
                "options": {
                    "SOURCE_MQTT_HOST": "old.local",
                    "UPSTREAM_FUTURE_OPTION": "keep-me",
                    "PUBLISH_SENSORS_RETAINED": True,
                    "FILTER_DATA_GLITCHES": True,
                }
            }
        if path == "/addons/self/options":
            return None
        raise AssertionError(path)

    monkeypatch.setattr(supervisor_config, "_supervisor_request", fake_request)

    merged = supervisor_config.save_addon_options(
        {
            "SOURCE_MQTT_HOST": "new.local",
            "KEEP_BATTERY_POSITION": True,
        }
    )

    assert merged["SOURCE_MQTT_HOST"] == "new.local"
    assert merged["KEEP_BATTERY_POSITION"] is True
    assert merged["UPSTREAM_FUTURE_OPTION"] == "keep-me"
    assert "PUBLISH_SENSORS_RETAINED" not in merged
    assert "FILTER_DATA_GLITCHES" not in merged

    save_call = calls[1]
    assert save_call == (
        "POST",
        "/addons/self/options",
        {"options": merged},
    )


def test_get_addon_options_hides_retired_retain_option_and_normalizes_timeout(monkeypatch):
    def fake_request(method, path, payload=None):
        if path == "/addons/self/info":
            return {
                "version": "3.1.41",
                "state": "started",
                "options": {
                    "PUBLISH_SENSORS_RETAINED": True,
                    "FILTER_DATA_GLITCHES": True,
                    "DEVICE_TIMEOUT": 0,
                },
            }
        if path == "/homeassistant/api/config":
            return {"language": "de"}
        raise AssertionError(path)

    monkeypatch.setattr(supervisor_config, "_supervisor_request", fake_request)

    result = supervisor_config.get_addon_options()

    assert "PUBLISH_SENSORS_RETAINED" not in result["options"]
    assert "FILTER_DATA_GLITCHES" not in result["options"]
    assert result["options"]["DEVICE_TIMEOUT"] == 120


def test_save_addon_options_uses_only_self_endpoints_allowed_to_addon(monkeypatch):
    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        if path == "/addons/self/info":
            return {"options": {"MAX_SLOTS": 1}}
        if path == "/addons/self/options":
            return None
        raise AssertionError(path)

    monkeypatch.setattr(supervisor_config, "_supervisor_request", fake_request)

    supervisor_config.save_addon_options({"MAX_SLOTS": 2})

    assert [path for _method, path, _payload in calls] == [
        "/addons/self/info",
        "/addons/self/options",
    ]
    assert all(path.count("/") <= 3 for _method, path, _payload in calls)


def test_all_ingress_configuration_options_are_normalized():
    options = dict(supervisor_config._DEFAULTS)

    normalized = supervisor_config.normalize_options(options)

    assert set(normalized) == set(supervisor_config._ALLOWED_OPTIONS)
    assert normalized["SOURCE_MQTT_PORT"] == 7006
    assert normalized["MAX_BAT"] == "auto"
    assert normalized["KEEP_BATTERY_POSITION"] is False


def test_schedule_restart_restarts_only_this_addon(monkeypatch):
    calls = []

    monkeypatch.setattr(supervisor_config.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(
        supervisor_config,
        "_supervisor_request",
        lambda method, path, payload=None: calls.append((method, path, payload)),
    )

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(supervisor_config.threading, "Thread", ImmediateThread)

    supervisor_config.schedule_restart()

    assert calls == [("POST", "/addons/self/restart", {})]
    assert all("/core/" not in path for _method, path, _payload in calls)


def test_get_home_assistant_language_uses_core_api(monkeypatch):
    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        return {"language": "de-DE"}

    monkeypatch.setattr(supervisor_config, "_supervisor_request", fake_request)

    assert supervisor_config.get_home_assistant_language() == "de-DE"
    assert calls == [("GET", "/homeassistant/api/config", None)]


def test_get_home_assistant_language_falls_back_on_api_error(monkeypatch):
    def fake_request(method, path, payload=None):
        raise supervisor_config.SupervisorConfigError("unavailable")

    monkeypatch.setattr(supervisor_config, "_supervisor_request", fake_request)

    assert supervisor_config.get_home_assistant_language() == "en"

def test_current_process_logs_filter_to_marker(monkeypatch):
    marker = supervisor_config._PROCESS_LOG_MARKER
    calls = []

    def fake_text_request(path):
        calls.append(path)
        return (
            "2026-09-06 18:26:33 [DEBUG] old entry\n"
            f"--- {marker} ---\n"
            "2026-09-30 21:44:00 [ERROR] current entry\n"
        )

    monkeypatch.setattr(
        supervisor_config,
        "_supervisor_text_request",
        fake_text_request,
    )

    result = supervisor_config.get_current_process_logs()

    assert calls == ["/addons/self/logs"]
    assert result["marker_found"] is True
    assert "old entry" not in result["logs"]
    assert "current entry" in result["logs"]


def test_current_process_logs_fall_back_to_process_start_when_marker_is_missing(monkeypatch):
    monkeypatch.setattr(
        supervisor_config,
        "_PROCESS_STARTED_AT",
        "2026-10-01T00:46:37+02:00",
    )
    monkeypatch.setattr(
        supervisor_config,
        "_supervisor_text_request",
        lambda _path: (
            "2026-09-30 23:59:59,000 [INFO] old entry\n"
            "2026-10-01 00:46:38,100 [INFO] current startup\n"
            "2026-10-01 00:46:39,200 [INFO] current follow-up\n"
        ),
    )

    result = supervisor_config.get_current_process_logs()

    assert result["marker_found"] is True
    assert "old entry" not in result["logs"]
    assert result["logs"].startswith("2026-10-01 00:46:38,100")
    assert "current follow-up" in result["logs"]


def test_current_process_logs_still_hide_old_history_without_current_lines(monkeypatch):
    monkeypatch.setattr(
        supervisor_config,
        "_PROCESS_STARTED_AT",
        "2026-10-01T00:46:37+02:00",
    )
    monkeypatch.setattr(
        supervisor_config,
        "_supervisor_text_request",
        lambda _path: "2026-09-30 23:59:59,000 [INFO] old entry\n",
    )

    result = supervisor_config.get_current_process_logs()

    assert result["marker_found"] is False
    assert result["logs"] == ""



def test_current_process_logs_continue_across_midnight(monkeypatch):
    monkeypatch.setattr(
        supervisor_config,
        "_PROCESS_STARTED_AT",
        "2026-10-01T22:39:27+02:00",
    )
    monkeypatch.setattr(
        supervisor_config,
        "_supervisor_text_request",
        lambda _path: (
            "2026-10-01 22:39:27,553 [INFO] Better GroBro started successfully\n"
            "2026-10-01 23:59:59,900 [INFO] before midnight\n"
            "2026-10-02 00:00:00,012 [INFO] after midnight\n"
            "2026-10-02 00:05:00,000 [INFO] still running\n"
        ),
    )

    result = supervisor_config.get_current_process_logs()

    assert result["marker_found"] is True
    assert "before midnight" in result["logs"]
    assert "after midnight" in result["logs"]
    assert "still running" in result["logs"]
