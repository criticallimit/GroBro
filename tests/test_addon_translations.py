from pathlib import Path

LANGUAGES = ("de", "en", "fr", "es", "nl")
CONFIG_KEYS = (
    "SOURCE_MQTT_HOST",
    "SOURCE_MQTT_PORT",
    "SOURCE_MQTT_TLS",
    "SOURCE_MQTT_USER",
    "SOURCE_MQTT_PASS",
    "TARGET_MQTT_HOST",
    "TARGET_MQTT_PORT",
    "TARGET_MQTT_TLS",
    "TARGET_MQTT_USER",
    "TARGET_MQTT_PASS",
    "MQTT_CLIENT_SUFFIX",
    "HA_BASE_TOPIC",
    "GROWATT_CLOUD",
    "GROWATT_CLOUD_CONFIG_FILTER",
    "LOG_LEVEL",
    "DUMP_MESSAGES",
    "DUMP_DIR",
    "REGISTER_DEBUG",
    "REGISTER_DEBUG_DIR",
    "REGISTER_DEBUG_MAX_REGISTER",
    "REGISTER_DEBUG_CHANGES_ONLY",
    "DEVICE_TIMEOUT",
    "MAX_SLOTS",
    "MAX_BAT",
    "AVAILABILITY_SENSOR",
    "TZ",
    "KEEP_BATTERY_POSITION",
)


def test_all_supported_languages_have_native_addon_configuration_translations():
    root = Path(__file__).resolve().parents[1] / "translations"

    for language in LANGUAGES:
        path = root / f"{language}.yaml"
        assert path.exists(), language
        text = path.read_text(encoding="utf-8")
        assert text.startswith("configuration:\n")
        for key in CONFIG_KEYS:
            assert f"  {key}:\n" in text, (language, key)
        assert "PUBLISH_SENSORS_RETAINED" not in text
        assert "FILTER_DATA_GLITCHES" not in text


def test_dutch_translation_is_real_not_english_copy():
    root = Path(__file__).resolve().parents[1] / "translations"
    dutch = (root / "nl.yaml").read_text(encoding="utf-8")

    assert "Maximaal aantal batterijen" in dutch
    assert "Apparaattime-out" in dutch
    assert "Stabiele batterijposities" in dutch
