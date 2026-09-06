"""Low-risk Home Assistant telemetry hot-path optimizations.

This module deliberately changes no entity, topic, register or control semantics.
It only combines repeated passes over one already-decoded telemetry payload into
one pass before publishing the same Home Assistant state JSON.
"""

from __future__ import annotations

import json
import logging

from grobro.ha import client as ha_client_module

LOG = logging.getLogger(__name__)
_INSTALLED = False


def _prepare_payload(client, state, effective_max_bat: int, known_registers):
    """Apply the existing HA value rules in one pass over the source payload."""
    input_registers = known_registers.input_registers if known_registers else None
    payload: dict = {}

    for key, raw_value in state.payload.items():
        bat_num = ha_client_module._get_bat_number(key)
        if bat_num is not None and bat_num > effective_max_bat:
            continue

        value = raw_value
        reg = input_registers.get(key) if input_registers is not None else None

        if reg is not None:
            if (
                key.startswith("bat")
                and key.endswith("_temp")
                and isinstance(value, (int, float))
                and value == -273.1
            ):
                value = None

            value = ha_client_module.map_enum_value(reg, value)

            if (
                ha_client_module.FILTER_DATA_GLITCHES
                and getattr(reg.homeassistant, "state_class", None) == "total_increasing"
                and isinstance(value, (int, float))
            ):
                device_key = (state.device_id, key)
                last_value = client._last_energy_values.get(device_key)
                if last_value is not None and value < last_value:
                    LOG.debug(
                        "Suppressed decrease for %s/%s: %.1f -> %.1f",
                        state.device_id,
                        key,
                        last_value,
                        value,
                    )
                    value = last_value
                else:
                    client._last_energy_values[device_key] = value

        payload[key] = value

    return payload


def install_ha_performance_hook() -> None:
    """Replace only HA input-state preparation with an equivalent single pass."""
    global _INSTALLED
    if _INSTALLED:
        return

    client_cls = ha_client_module.Client

    def publish_input_register_fast(self, state):
        LOG.debug("HA: publish: %s", state)
        effective_max_bat = ha_client_module._resolve_max_bat(
            state.device_id,
            state.payload,
        )
        self._Client__detect_neo_pv_count(state.device_id, state.payload)
        self._Client__publish_device_discovery(state.device_id, effective_max_bat)
        self._Client__publish_availability(state.device_id, True)
        if ha_client_module.DEVICE_TIMEOUT > 0:
            self._Client__reset_device_timer(state.device_id)

        known_registers = ha_client_module.get_known_registers(state.device_id)
        payload = _prepare_payload(
            self,
            state,
            effective_max_bat,
            known_registers,
        )

        # Combine battery serial parts into single values.
        for bat_num in range(2, 5):
            parts = []
            for index in range(1, 5):
                key = f"bat{bat_num}_ser_part_{index}"
                value = payload.pop(key, None)
                if value is not None:
                    parts.append(str(value))
            combined = "".join(parts).strip()
            if combined:
                payload[f"bat{bat_num}_serial"] = combined
            else:
                payload.pop(f"bat{bat_num}_serial", None)

        # Preserve optional battery-position tracking exactly as before.
        if ha_client_module.KEEP_BATTERY_POSITION:
            current_serials: dict[int, str] = {}
            for bat_num in range(2, 5):
                key = f"bat{bat_num}_serial"
                if key in payload and payload[key]:
                    current_serials[bat_num] = str(payload[key])
            previous_serials = ha_client_module._LAST_BAT_SERIALS.get(
                state.device_id,
                {},
            )
            if previous_serials and current_serials:
                for pos, serial in current_serials.items():
                    for previous_pos, previous_serial in previous_serials.items():
                        if serial == previous_serial and pos != previous_pos:
                            LOG.warning(
                                "Battery %s moved from Bat%d to Bat%d for device %s — inverter re-enumeration detected",
                                serial,
                                previous_pos,
                                pos,
                                state.device_id,
                            )
            ha_client_module._LAST_BAT_SERIALS[state.device_id] = current_serials

        topic = f"{ha_client_module.HA_BASE_TOPIC}/grobro/{state.device_id}/state"
        self._client.publish(
            topic,
            json.dumps(payload, separators=(",", ":")),
            retain=ha_client_module.PUBLISH_SENSORS_RETAINED,
        )

    client_cls.publish_input_register = publish_input_register_fast
    _INSTALLED = True
    LOG.info("Installed GroBro Home Assistant telemetry performance hook")
