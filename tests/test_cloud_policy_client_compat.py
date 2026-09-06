from unittest.mock import patch

import grobro.grobro.client as client_module


def test_legacy_cloud_flags_resolve_through_policy():
    with (
        patch.object(client_module, "GROWATT_CLOUD_ENABLED", True),
        patch.object(client_module, "_cloud_lower", "true"),
        patch.object(client_module, "GROWATT_CLOUD_FILTER", set()),
        patch.object(client_module, "GROWATT_CLOUD_CONFIG_FILTER", "false"),
    ):
        policy = client_module._current_cloud_policy()
        assert policy.allows_device("0PVPTEST") is True
        assert policy.should_block_cloud_message(0x0118) is False


def test_legacy_allowlist_resolves_through_policy():
    with (
        patch.object(client_module, "GROWATT_CLOUD_ENABLED", True),
        patch.object(client_module, "_cloud_lower", "0pvptest"),
        patch.object(client_module, "GROWATT_CLOUD", "0PVPTEST"),
        patch.object(client_module, "GROWATT_CLOUD_FILTER", {"0PVPTEST"}),
        patch.object(client_module, "GROWATT_CLOUD_CONFIG_FILTER", "true"),
    ):
        policy = client_module._current_cloud_policy()
        assert policy.allows_device("0PVPTEST") is True
        assert policy.allows_device("QMNTEST") is False
        assert policy.should_block_cloud_message(0x0118) is True


def test_legacy_disabled_flag_wins_over_other_values():
    with (
        patch.object(client_module, "GROWATT_CLOUD_ENABLED", False),
        patch.object(client_module, "_cloud_lower", "true"),
        patch.object(client_module, "GROWATT_CLOUD", "true"),
    ):
        policy = client_module._current_cloud_policy()
        assert policy.enabled is False
        assert policy.allows_device("0PVPTEST") is False
