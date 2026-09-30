import json
import re
from pathlib import Path

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

def test_idiomatic_domain_translations_are_complete_and_not_mechanical():
    import grobro.ha.localization as localization

    expected_sources = {
        "Battery SOC",
        "Battery Health",
        "Battery Cycle Count",
        "Grid import power",
        "Grid export power",
        "Load power",
        "Derating Mode",
        "PV ISO value",
        "GFCI Curr",
        "R DCI Curr",
        "Inverter output PF now",
        "Current status of DryContact",
        "Pack Information from BMS",
        "Using Cap from BMS",
        "Delta V from BMS",
        "Island Mode Enabled",
        "Power factor",
    }

    for language in ("de", "fr", "es", "nl"):
        assert expected_sources <= set(localization._IDIOMATIC_EXACT[language])
        for source in expected_sources:
            translated = translate_entity_name(source, language)
            assert translated
            assert translated != source

    assert translate_entity_name("Battery SOC", "de") == "Ladezustand"
    assert translate_entity_name("Battery SOC", "fr") == "État de charge"
    assert translate_entity_name("Battery SOC", "es") == "Estado de carga"
    assert translate_entity_name("Battery SOC", "nl") == "Laadstatus"

    assert translate_entity_name("Load power", "de") == "Verbrauchsleistung"
    assert translate_entity_name("Load power", "fr") == "Puissance consommée"
    assert translate_entity_name("Load power", "es") == "Potencia de consumo"
    assert translate_entity_name("Load power", "nl") == "Verbruiksvermogen"

    assert translate_entity_name("Battery 2 max. Cell Voltage", "de") == "Maximale Zellspannung Batterie 2"
    assert translate_entity_name("Battery 2 min. Cell Voltage", "de") == "Minimale Zellspannung Batterie 2"
    assert translate_entity_name("Battery 3 max. Cell Voltage", "de") == "Maximale Zellspannung Batterie 3"
    assert translate_entity_name("Battery 3 min. Cell Voltage", "de") == "Minimale Zellspannung Batterie 3"

    assert translate_entity_name("Current status of DryContact", "de") == "Status des potentialfreien Kontakts"
    assert translate_entity_name("Current status of DryContact", "fr") == "État du contact sec"
    assert translate_entity_name("Current status of DryContact", "es") == "Estado del contacto seco"
    assert translate_entity_name("Current status of DryContact", "nl") == "Status van het potentiaalvrije contact"


def test_idiomatic_translation_tables_stay_in_sync():
    import grobro.ha.localization as localization

    source_sets = {
        language: set(mapping)
        for language, mapping in localization._IDIOMATIC_EXACT.items()
    }
    assert source_sets["de"] == source_sets["fr"] == source_sets["es"] == source_sets["nl"]


def test_idiomatic_translation_does_not_change_technical_identity(monkeypatch):
    import grobro.ha.discovery_runtime as discovery_runtime

    monkeypatch.setattr(discovery_runtime, "runtime_language", lambda: "de")
    client = SimpleNamespace(_config_cache={})
    device_id = "QMNTEST0000002"
    component_id = f"grobro_{device_id}_battery_soc"
    data = {
        "dev": {"identifiers": [device_id]},
        "o": {"name": "grobro", "url": "https://example.invalid"},
        "cmps": {
            component_id: {
                "platform": "sensor",
                "name": "Battery SOC",
                "unique_id": component_id,
                "state_topic": f"homeassistant/grobro/{device_id}/state",
                "value_template": "{{ value_json['SOC'] }}",
            }
        },
    }

    cleaned = clean_discovery_payload(client, device_id, data)
    component = cleaned["cmps"][component_id]
    assert component["name"] == "Ladezustand"
    assert component["unique_id"] == component_id
    assert component["state_topic"] == f"homeassistant/grobro/{device_id}/state"
    assert component["value_template"] == "{{ value_json['SOC'] }}"

def test_all_register_display_names_are_localization_covered():
    import grobro.ha.localization as localization

    root = Path(__file__).resolve().parents[1] / "grobro" / "model"
    register_files = (
        "growatt_mod_registers.json",
        "growatt_neo_registers.json",
        "growatt_nexa_registers.json",
        "growatt_noah_registers.json",
        "growatt_spf_registers.json",
        "growatt_xh2_registers.json",
    )

    names = set()

    def collect(value):
        if isinstance(value, dict):
            name = value.get("name")
            if isinstance(name, str) and name.strip():
                names.add(name.strip())
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for filename in register_files:
        collect(json.loads((root / filename).read_text(encoding="utf-8")))

    # Guard against accidentally testing only a small subset after schema changes.
    assert len(names) >= 300

    word_re = re.compile(r"[A-Za-z]+")
    for language in ("de", "fr", "es", "nl"):
        word_map = localization._WORDS[language]
        for source in sorted(names):
            translated = translate_entity_name(source, language)
            assert translated
            # Every source word for which this language has a genuinely different
            # localized term must disappear from the visible result. Technical
            # acronyms and internationally identical terms are intentionally allowed.
            translated_words = {word.lower() for word in word_re.findall(translated)}
            for source_word in word_re.findall(source):
                target_word = word_map.get(source_word.lower())
                if target_word is None:
                    continue
                target_tokens = {
                    token.lower() for token in word_re.findall(target_word)
                }
                if source_word.lower() in target_tokens:
                    continue
                assert source_word.lower() not in translated_words, (
                    language,
                    source,
                    translated,
                    source_word,
                )

