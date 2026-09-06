import pytest

from grobro.grobro.cloud_policy import CloudForwardingPolicy


@pytest.mark.parametrize("value", [None, "", "false", "False", "0", "no", "off"])
def test_false_values_disable_cloud_forwarding(value):
    policy = CloudForwardingPolicy.parse(value)
    assert policy.enabled is False
    assert policy.allowlist == frozenset()
    assert policy.forwards_all_devices is False
    assert policy.allows_device("0PVPTEST") is False


def test_true_enables_all_devices():
    policy = CloudForwardingPolicy.parse("true")
    assert policy.enabled is True
    assert policy.allowlist == frozenset()
    assert policy.forwards_all_devices is True
    assert policy.allows_device("0PVPTEST") is True
    assert policy.allows_device("QMNTEST") is True


def test_comma_separated_value_is_an_allowlist():
    policy = CloudForwardingPolicy.parse("0PVPTEST, QMNTEST ,, ")
    assert policy.enabled is True
    assert policy.allowlist == frozenset({"0PVPTEST", "QMNTEST"})
    assert policy.forwards_all_devices is False
    assert policy.allows_device("0PVPTEST") is True
    assert policy.allows_device("QMNTEST") is True
    assert policy.allows_device("OTHER") is False


def test_config_filter_blocks_only_configuration_message_types():
    policy = CloudForwardingPolicy.parse("true", "true")
    assert policy.block_config_commands is True
    assert policy.should_block_cloud_message(0x0118) is True
    assert policy.should_block_cloud_message(0x0110) is True
    assert policy.should_block_cloud_message(0x0104) is False


def test_config_filter_is_disabled_by_default():
    policy = CloudForwardingPolicy.parse("true")
    assert policy.block_config_commands is False
    assert policy.should_block_cloud_message(0x0118) is False
