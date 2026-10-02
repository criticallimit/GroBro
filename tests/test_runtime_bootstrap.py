from unittest.mock import patch

from grobro.ha_bridge import install_runtime_layers


def test_runtime_layers_install_in_stable_order():
    calls = []

    with patch(
        "grobro.ha_bridge.install_raw_dump_hook",
        side_effect=lambda: calls.append("raw_dump"),
    ), patch(
        "grobro.ha_bridge.install_noah_heater_hook",
        side_effect=lambda: calls.append("noah_heater"),
    ), patch(
        "grobro.ha_bridge.install_ha_performance_hook",
        side_effect=lambda: calls.append("ha_performance"),
    ):
        install_runtime_layers()

    assert calls[:3] == [
        "raw_dump",
        "noah_heater",
        "ha_performance",
    ]
