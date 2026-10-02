from unittest.mock import patch

from grobro.ha import cleanup


def test_ha_cleanup_installs_only_discovery_runtime():
    cleanup._INSTALLED = False
    calls = []

    with patch(
        "grobro.ha.cleanup.install_discovery_runtime",
        side_effect=lambda *_: calls.append("discovery"),
    ):
        cleanup.install_ha_cleanup_hook()
        cleanup.install_ha_cleanup_hook()

    assert calls == ["discovery"]
