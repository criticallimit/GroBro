"""Initial NEO Inverter Power state read for Home Assistant."""

from __future__ import annotations

import grobro.model as model
from grobro.ha import client as ha_client_module
from grobro.model.modbus_message import GrowattModbusFunction


def request_initial_neo_inverter_power(client, device_id: str) -> bool:
    """Request NEO holding register 0 once so the HA switch gets an initial state."""
    if not model.is_family(device_id, "neo"):
        return False

    requested = getattr(client, "_neo_inverter_power_read_requested", None)
    if requested is None:
        requested = set()
        client._neo_inverter_power_read_requested = requested
    if device_id in requested:
        return False

    known = model.get_known_registers(device_id)
    if not known:
        return False
    register = known.holding_registers.get("inverter_power")
    if not register or not callable(getattr(client, "on_command", None)):
        return False

    client.on_command(
        ha_client_module.make_modbus_command(
            device_id,
            GrowattModbusFunction.READ_SINGLE_REGISTER,
            register.growatt.position.register_no,
        )
    )
    requested.add(device_id)
    return True


def clear_neo_inverter_power_read_cache(client) -> None:
    requested = getattr(client, "_neo_inverter_power_read_requested", None)
    if requested is not None:
        requested.clear()


def install_neo_power_runtime() -> None:
    """Trigger the initial read when live NEO telemetry arrives."""
    client_cls = ha_client_module.Client
    original_publish_input = client_cls.publish_input_register

    def publish_input_with_neo_power_read(self, state):
        result = original_publish_input(self, state)
        request_initial_neo_inverter_power(self, state.device_id)
        return result

    client_cls.publish_input_register = publish_input_with_neo_power_read
