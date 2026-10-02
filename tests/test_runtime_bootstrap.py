import grobro.ha_bridge as bridge


def test_bridge_has_no_runtime_hook_bootstrap():
    assert not hasattr(bridge, "install_runtime_layers")
