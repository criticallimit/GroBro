from unittest.mock import patch

from grobro.grobro.runtime import install_runtime_layers


def test_runtime_layers_install_in_stable_order():
    calls = []

    with patch("grobro.grobro.runtime.install_grobro_cleanup_hook", side_effect=lambda: calls.append("grobro_cleanup")), patch(
        "grobro.grobro.runtime.install_ha_cleanup_hook", side_effect=lambda: calls.append("ha_cleanup")
    ), patch(
        "grobro.grobro.runtime.install_ha_performance_hook", side_effect=lambda: calls.append("ha_performance")
    ), patch(
        "grobro.grobro.runtime.install_system_time_entity_cleanup", side_effect=lambda: calls.append("system_time_cleanup")
    ):
        install_runtime_layers()

    assert calls == [
        "grobro_cleanup",
        "ha_cleanup",
        "ha_performance",
        "system_time_cleanup",
    ]
