"""NEO Inverter Power state handling for Home Assistant."""

from __future__ import annotations

import grobro.model as model
from grobro.ha import client as ha_client_module
from grobro.ha.timer_runtime import daemon_timer, guard_runtime, runtime_lock
from grobro.model.mqtt_config import publish_succeeded
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

    try:
        result = client.on_command(
            ha_client_module.make_modbus_command(
                device_id,
                GrowattModbusFunction.READ_SINGLE_REGISTER,
                register.growatt.position.register_no,
            )
        )
    except Exception as exc:
        ha_client_module.LOG.warning("Could not request initial NEO inverter power for %s (%s)", device_id, exc)
        return False
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


@guard_runtime
def schedule_known_neo_state_probe(client, delay: float = 1.0) -> None:
    """Probe known NEOs after startup/recovery and retry briefly if MQTT is not ready."""
    previous = getattr(client, "_neo_startup_probe_timer", None)
    if previous is not None:
        try:
            previous.cancel()
        except Exception:
            pass

    def schedule_probe(interval, attempt):
        def run():
            with runtime_lock(client):
                if getattr(client, "_stopped", False) or client._neo_startup_probe_timer is not timer:
                    return
                run_probe(attempt)

        client._neo_startup_probe_timer = None
        try:
            timer = daemon_timer(interval, run)
            client._neo_startup_probe_timer = timer
            timer.start()
        except (RuntimeError, OSError) as exc:
            client._neo_startup_probe_timer = None
            ha_client_module.LOG.warning("Could not schedule NEO state probe (%s)", exc)

    def run_probe(attempt):
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

        schedule_probe(2.0 * (attempt + 1), attempt + 1)

    schedule_probe(delay, 0)


def _publish_retained_switch_state(client, device_id: str, state: str) -> None:
    result = client._client.publish(
        f"{ha_client_module.HA_BASE_TOPIC}/switch/grobro/{device_id}/inverter_power/get",
        state,
        retain=True,
    )
    if publish_succeeded(result):
        # A subsequent real readback must correct this optimistic state, even
        # when it equals the last real value from before the user command.
        cache = getattr(client, "_last_holding_state", None)
        if cache is not None:
            cache.pop((device_id, "inverter_power"), None)
