from grobro import ha_bridge as diagnostics


def test_install_optional_diagnostics_is_compatibility_noop():
    assert diagnostics.install_optional_diagnostics() is None
