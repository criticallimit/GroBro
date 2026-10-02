from grobro.ha import cleanup


def test_ha_cleanup_hook_is_compatibility_noop():
    assert cleanup.install_ha_cleanup_hook() is None
