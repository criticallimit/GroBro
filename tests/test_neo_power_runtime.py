from types import SimpleNamespace

from grobro.ha.availability import clear_reconnect_caches
from grobro.ha.neo_power_runtime import request_initial_neo_inverter_power
from grobro.model.modbus_message import GrowattModbusFunction


def test_initial_neo_inverter_power_read_is_sent_once():
    commands = []
    client = SimpleNamespace(
        on_command=commands.append,
        _neo_inverter_power_read_requested=set(),
    )

    assert request_initial_neo_inverter_power(client, "QMNTEST") is True
    assert request_initial_neo_inverter_power(client, "QMNTEST") is False
    assert len(commands) == 1

    command = commands[0]
    assert command.device_id == "QMNTEST"
    assert command.function == GrowattModbusFunction.READ_SINGLE_REGISTER
    assert command.register_no == 0


def test_non_neo_does_not_request_inverter_power():
    commands = []
    client = SimpleNamespace(
        on_command=commands.append,
        _neo_inverter_power_read_requested=set(),
    )

    assert request_initial_neo_inverter_power(client, "0PVPTEST") is False
    assert request_initial_neo_inverter_power(client, "0HVRTEST") is False
    assert commands == []


def test_reconnect_allows_initial_neo_read_again():
    commands = []
    client = SimpleNamespace(
        on_command=commands.append,
        _neo_inverter_power_read_requested={"QMNTEST"},
        _last_availability={},
        _discovery_signature={},
        _discovery_payload_cache={},
        _last_state_payload={},
        _discovery_cache=[],
    )

    clear_reconnect_caches(client)

    assert request_initial_neo_inverter_power(client, "QMNTEST") is True
    assert len(commands) == 1
