from types import SimpleNamespace

from grobro.ha.discovery_runtime import clean_discovery_payload
from grobro.ha.localization import (
    normalize_language,
    reset_language_cache,
    translate_entity_name,
)


def test_supported_language_normalization_includes_dutch():
    assert normalize_language("nl-NL") == "nl"
    assert normalize_language("de-DE") == "de"
    assert normalize_language("fr-FR") == "fr"
    assert normalize_language("es-ES") == "es"
    assert normalize_language("en-US") == "en"
    assert normalize_language("xx") == "en"


def test_common_entity_names_translate_without_touching_technical_identity():
    assert translate_entity_name("Grid frequency", "de") == "Netzfrequenz"
    assert translate_entity_name("Grid frequency", "fr") == "Fréquence du réseau"
    assert translate_entity_name("Grid frequency", "es") == "Frecuencia de red"
    assert translate_entity_name("Grid frequency", "nl") == "Netfrequentie"
    assert translate_entity_name("Grid frequency", "en") == "Grid frequency"

    assert translate_entity_name("Restart Datalogger", "nl") == "Datalogger herstarten"
    assert translate_entity_name("Slot 3 Power", "de") == "Slot 3 Leistung"
    assert translate_entity_name("Bat2 Serial", "nl") == "Bat2 serienummer"


def test_register_style_names_are_localized_by_fallback_rules():
    assert translate_entity_name("Battery voltage from BMS", "de") != "Battery voltage from BMS"
    assert translate_entity_name("Battery voltage from BMS", "fr") != "Battery voltage from BMS"
    assert translate_entity_name("Battery voltage from BMS", "es") != "Battery voltage from BMS"
    assert translate_entity_name("Battery voltage from BMS", "nl") != "Battery voltage from BMS"


def test_discovery_localizes_only_display_name(monkeypatch):
    import grobro.ha.discovery_runtime as discovery_runtime

    monkeypatch.setattr(discovery_runtime, "runtime_language", lambda: "nl")
    client = SimpleNamespace(_config_cache={})
    device_id = "QMNTEST0000001"
    data = {
        "dev": {"identifiers": [device_id]},
        "o": {"name": "grobro", "url": "https://example.invalid"},
        "cmps": {
            f"grobro_{device_id}_grid_frequency": {
                "platform": "sensor",
                "name": "Grid frequency",
                "unique_id": f"grobro_{device_id}_grid_frequency",
                "state_topic": f"homeassistant/grobro/{device_id}/state",
                "value_template": "{{ value_json['Fac'] }}",
            }
        },
    }

    cleaned = clean_discovery_payload(client, device_id, data)
    component = cleaned["cmps"][f"grobro_{device_id}_grid_frequency"]

    assert component["name"] == "Netfrequentie"
    assert component["unique_id"] == f"grobro_{device_id}_grid_frequency"
    assert component["state_topic"] == f"homeassistant/grobro/{device_id}/state"
    assert component["value_template"] == "{{ value_json['Fac'] }}"


def test_language_cache_can_be_reset():
    reset_language_cache()
