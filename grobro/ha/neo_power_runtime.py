"""NEO Inverter Power state handling for Home Assistant."""

from __future__ import annotations

import grobro.model as model
from grobro.ha import client as ha_client_module
from grobro.model.modbus_message import GrowattModbusFunction


def request_initial_neo_inverter_power(client, device_id: str) -> bool:
    """Request NEO holding register 0 once when the device becomes live.

    Some NEO firmware versions do not return a usable value for this standalone
    read. The request is therefore best-effort only; persisted command/readback
    state below is the authoritative HA fallback.
    """
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


def _publish_retained_switch_state(client, device_id: str, state: str) -> None:
    client._client.publish(
        f"{ha_client_module.HA_BASE_TOPIC}/switch/grobro/{device_id}/inverter_power/get",
        state,
        retain=True,
    )


def install_neo_power_runtime() -> None:
    """Keep the NEO Inverter Power switch state known across restarts.

    The upstream switch command path is preserved. Better GroBro only adds a
    retained state mirror because some NEO firmware does not answer a standalone
    holding-register-0 read. A real holding-register readback, when available, is
    also retained and therefore replaces the fallback state.
    """
    client_cls = ha_client_module.Client

    original_publish_input = client_cls.publish_input_register

    def publish_input_with_neo_power_read(self, state):
        result = original_publish_input(self, state)
        request_initial_neo_inverter_power(self, state.device_id)
        return result

    client_cls.publish_input_register = publish_input_with_neo_power_read

    original_on_message = client_cls._Client__on_message

    def on_message_with_neo_power_state(self, client, userdata, msg):
        topic = str(msg.topic)
        parts = topic.removeprefix(f"{ha_client_module.HA_BASE_TOPIC}/").split("/")
        is_neo_power_set = (
            len(parts) == 5
            and parts[0] == "switch"
            and parts[1] == "grobro"
            and parts[3] == "inverter_power"
            and parts[4] == "set"
            and model.is_family(parts[2], "neo")
        )

        result = original_on_message(self, client, userdata, msg)

        if is_neo_power_set:
            raw = msg.payload.decode(errors="ignore").strip().upper()
            if raw in {"ON", "OFF"}:
                _publish_retained_switch_state(self, parts[2], raw)
        return result

    client_cls._Client__on_message = on_message_with_neo_power_state

    original_publish_holding = client_cls.publish_holding_register_input

    def publish_holding_with_retained_neo_power(self, ha_input):
        result = original_publish_holding(self, ha_input)
        if model.is_family(ha_input.device_id, "neo"):
            for value in ha_input.payload:
                if value.name == "inverter_power" and value.value in {"ON", "OFF"}:
                    _publish_retained_switch_state(
                        self,
                        ha_input.device_id,
                        value.value,
                    )
        return result

    client_cls.publish_holding_register_input = publish_holding_with_retained_neo_power
