from grobro.ha_bridge import install_runtime_layers


def test_runtime_layers_is_compatibility_noop():
    assert install_runtime_layers() is None
