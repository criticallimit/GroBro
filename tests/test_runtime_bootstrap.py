from unittest.mock import patch

from grobro.grobro.runtime import install_runtime_layers


def test_runtime_layers_install_in_stable_order():
    calls = []

    with patch(
        "grobro.grobro.runtime.install_raw_dump_hook",
        side_effect=lambda: calls.append("raw_dump"),
    ), patch(
        "grobro.grobro.runtime.install_noah_heater_hook",
        side_effect=lambda: calls.append("noah_heater"),
    ), patch(
        "grobro.grobro.runtime.install_ha_cleanup_hook",
        side_effect=lambda: calls.append("ha_cleanup"),
    ), patch(
        "grobro.grobro.runtime.install_ha_performance_hook",
        side_effect=lambda: calls.append("ha_performance"),
    ):
        install_runtime_layers()

    assert calls == [
        "raw_dump",
        "noah_heater",
        "ha_cleanup",
        "ha_performance",
    ]
