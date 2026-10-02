"""NEO Inverter Power state handling for Home Assistant."""

from __future__ import annotations

import grobro.model as model
from grobro.ha import client as ha_client_module
from grobro.ha.timer_runtime import daemon_timer
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

    result = client.on_command(
        ha_client_module.make_modbus_command(
            device_id,
            GrowattModbusFunction.READ_SINGLE_REGISTER,
            register.growatt.position.register_no,
        )
    )
    status = getattr(result, "rc", None)
    if status is None:
        try:
            status = result[0]
        except (TypeError, IndexError, KeyError):
            status = None
    if status not in (None, 0):
        return False

    requested.add(device_id)
    return True


def clear_neo_inverter_power_read_cache(client) -> None:
    requested = getattr(client, "_neo_inverter_power_read_requested", None)
    if requested is not None:
        requested.clear()


def request_known_neo_states(client) -> int:
    """Actively probe persisted NEO devices instead of waiting for telemetry."""
    requested = 0
    for device_id in tuple(getattr(client, "_config_cache", {})):
        if request_initial_neo_inverter_power(client, device_id):
            requested += 1
    return requested


def schedule_known_neo_state_probe(client, delay: float = 1.0) -> None:
    """Probe known NEOs after startup/recovery and retry briefly if MQTT is not ready."""
    previous = getattr(client, "_neo_startup_probe_timer", None)
    if previous is not None:
        try:
            previous.cancel()
        except Exception:
            pass

    def run(attempt: int = 0):
        client._neo_startup_probe_timer = None
        request_known_neo_states(client)

        known_neos = {
            device_id
            for device_id in getattr(client, "_config_cache", {})
            if model.is_family(device_id, "neo")
        }
        requested = getattr(client, "_neo_inverter_power_read_requested", set())
        if known_neos.issubset(requested) or attempt >= 3:
            return

        timer = daemon_timer(2.0 * (attempt + 1), run, args=(attempt + 1,))
        client._neo_startup_probe_timer = timer
        timer.start()

    timer = daemon_timer(delay, run)
    client._neo_startup_probe_timer = timer
    timer.start()


def _publish_retained_switch_state(client, device_id: str, state: str) -> None:
    client._client.publish(
        f"{ha_client_module.HA_BASE_TOPIC}/switch/grobro/{device_id}/inverter_power/get",
        state,
        retain=True,
    )


def install_neo_power_runtime() -> None:
    """Install only the NEO switch-state mirror that cannot live in telemetry.

    Startup/recovery probing is now called directly by Client.start() and
    Client.__recover_after_home_assistant_restart(), so this hook no longer
    wraps those lifecycle methods.
    """
    client_cls = ha_client_module.Client
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

