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
        if path == "/addons/self/options/validate":
            return {"valid": True, "message": None}
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

    validate_call = calls[1]
    save_call = calls[2]
    assert validate_call[0:2] == ("POST", "/addons/self/options/validate")
    assert validate_call[2]["UPSTREAM_FUTURE_OPTION"] == "keep-me"
    assert "PUBLISH_SENSORS_RETAINED" not in validate_call[2]
    assert "FILTER_DATA_GLITCHES" not in validate_call[2]
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


def test_save_addon_options_stops_on_supervisor_validation_failure(monkeypatch):
    def fake_request(method, path, payload=None):
        if path == "/addons/self/info":
            return {"options": {}}
        if path == "/addons/self/options/validate":
            return {"valid": False, "message": "bad config"}
        raise AssertionError("save must not be called after failed validation")

    monkeypatch.setattr(supervisor_config, "_supervisor_request", fake_request)

    with pytest.raises(supervisor_config.SupervisorConfigError, match="bad config"):
        supervisor_config.save_addon_options({"MAX_SLOTS": 2})


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
