from unittest.mock import patch

from grobro.ha_bridge import install_runtime_layers


def test_runtime_layers_install_remaining_protocol_hook():
    calls = []

    with patch(
        "grobro.ha_bridge.install_raw_dump_hook",
        side_effect=lambda: calls.append("raw_dump"),
    ):
        install_runtime_layers()

    assert calls == ["raw_dump"]
