import grobro.ha_bridge as bridge


def test_bridge_has_no_diagnostic_hook_bootstrap():
    assert not hasattr(bridge, "install_optional_diagnostics")
