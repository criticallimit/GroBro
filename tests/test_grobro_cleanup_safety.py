from types import SimpleNamespace

from grobro.grobro.cleanup import _get_property_safe, _safe_topic_segment


def test_safe_topic_segment_blocks_path_traversal():
    assert _safe_topic_segment("..") == "_"
    assert _safe_topic_segment("../secret") == "_secret"
    assert _safe_topic_segment("0PVP50ZR175T00E8") == "0PVP50ZR175T00E8"


def test_get_property_safe_handles_missing_properties():
    assert _get_property_safe(SimpleNamespace(properties=None), "forwarded-for") is None


def test_get_property_safe_reads_user_property():
    props = SimpleNamespace(
        json=lambda: {"UserProperty": [("forwarded-for", "growatt")]}
    )
    msg = SimpleNamespace(properties=props)
    assert _get_property_safe(msg, "forwarded-for") == "growatt"
