from unittest.mock import patch

from grobro.ha import cleanup


def test_ha_cleanup_installs_only_remaining_runtime_hooks():
    cleanup._INSTALLED = False
    calls = []

    with patch(
        "grobro.ha.cleanup.install_battery_runtime_helpers",
        side_effect=lambda: calls.append("battery"),
    ), patch(
        "grobro.ha.cleanup.install_neo_power_runtime",
        side_effect=lambda: calls.append("neo_power"),
    ), patch(
        "grobro.ha.cleanup.install_discovery_runtime",
        side_effect=lambda *_: calls.append("discovery"),
    ):
        cleanup.install_ha_cleanup_hook()
        cleanup.install_ha_cleanup_hook()

    assert calls == [
        "battery",
        "neo_power",
        "discovery",
    ]
