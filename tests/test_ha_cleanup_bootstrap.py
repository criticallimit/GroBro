from unittest.mock import patch

from grobro.ha import cleanup


def test_split_ha_cleanup_installs_in_stable_order():
    cleanup._INSTALLED = False
    calls = []

    with patch("grobro.ha.cleanup.install_battery_runtime_helpers", side_effect=lambda: calls.append("battery")), patch(
        "grobro.ha.cleanup.install_state_runtime", side_effect=lambda: calls.append("state")
    ), patch(
        "grobro.ha.cleanup.install_config_runtime", side_effect=lambda *_: calls.append("config")
    ), patch(
        "grobro.ha.cleanup.install_time_sync_runtime", side_effect=lambda: calls.append("time_sync")
    ), patch(
        "grobro.ha.cleanup.install_pv_runtime", side_effect=lambda: calls.append("pv")
    ), patch(
        "grobro.ha.cleanup.install_availability_runtime", side_effect=lambda: calls.append("availability")
    ), patch(
        "grobro.ha.cleanup.install_timer_runtime", side_effect=lambda: calls.append("timer")
    ), patch(
        "grobro.ha.cleanup.install_discovery_runtime", side_effect=lambda *_: calls.append("discovery")
    ):
        cleanup.install_ha_cleanup_hook()
        cleanup.install_ha_cleanup_hook()

    assert calls == [
        "battery",
        "state",
        "config",
        "time_sync",
        "pv",
        "availability",
        "timer",
        "discovery",
    ]
