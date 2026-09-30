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
    monkeypatch.setattr(
        supervisor_config,
        "_supervisor_request",
        lambda method, path, payload=None: {
            "version": "3.1.28",
            "state": "started",
            "options": {"SOURCE_MQTT_HOST": "growatt.local"},
        },
    )

    result = supervisor_config.get_addon_options()

    assert result["version"] == "3.1.28"
    assert result["state"] == "started"
    assert result["options"]["SOURCE_MQTT_HOST"] == "growatt.local"
    assert result["options"]["TARGET_MQTT_PORT"] == 1883
    assert result["options"]["REGISTER_DEBUG"] is False


def test_save_addon_options_validates_then_updates_and_preserves_unknown(monkeypatch):
    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        if path == "/addons/self/info":
            return {
                "options": {
                    "SOURCE_MQTT_HOST": "old.local",
                    "UPSTREAM_FUTURE_OPTION": "keep-me",
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

    validate_call = calls[1]
    save_call = calls[2]
    assert validate_call[0:2] == ("POST", "/addons/self/options/validate")
    assert validate_call[2]["UPSTREAM_FUTURE_OPTION"] == "keep-me"
    assert save_call == (
        "POST",
        "/addons/self/options",
        {"options": merged},
    )


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
