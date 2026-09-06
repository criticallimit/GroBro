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
    input_get = input_registers.get if input_registers is not None else None
    get_bat_number = ha_client_module._get_bat_number
    map_enum_value = ha_client_module.map_enum_value
    filter_data_glitches = ha_client_module.FILTER_DATA_GLITCHES
    last_energy_values = client._last_energy_values
    device_id = state.device_id
    payload: dict = {}

    for key, raw_value in state.payload.items():
        bat_num = get_bat_number(key)
        if bat_num is not None and bat_num > effective_max_bat:
            continue

        value = raw_value
        reg = input_get(key) if input_get is not None else None

        if reg is not None:
            if (
                isinstance(value, (int, float))
                and value == -273.1
                and key.startswith("bat")
                and key.endswith("_temp")
            ):
                value = None

            value = map_enum_value(reg, value)

            if (
                filter_data_glitches
                and getattr(reg.homeassistant, "state_class", None) == "total_increasing"
                and isinstance(value, (int, float))
            ):
                device_key = (device_id, key)
                last_value = last_energy_values.get(device_key)
                if last_value is not None and value < last_value:
                    LOG.debug(
                        "Suppressed decrease for %s/%s: %.1f -> %.1f",
                        device_id,
                        key,
                        last_value,
                        value,
                    )
                    value = last_value
                else:
                    last_energy_values[device_key] = value

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
        device_id = state.device_id
        state_payload = state.payload
        effective_max_bat = ha_client_module._resolve_max_bat(
            device_id,
            state_payload,
        )
        self._Client__detect_neo_pv_count(device_id, state_payload)
        self._Client__publish_device_discovery(device_id, effective_max_bat)
        self._Client__publish_availability(device_id, True)
        if ha_client_module.DEVICE_TIMEOUT > 0:
            self._Client__reset_device_timer(device_id)

        known_registers = ha_client_module.get_known_registers(device_id)
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
                device_id,
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
                                device_id,
                            )
            ha_client_module._LAST_BAT_SERIALS[device_id] = current_serials

        topic = f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/state"
        self._client.publish(
            topic,
            json.dumps(payload, separators=(",", ":")),
            retain=ha_client_module.PUBLISH_SENSORS_RETAINED,
        )

    client_cls.publish_input_register = publish_input_register_fast
    _INSTALLED = True
    LOG.info("Installed GroBro Home Assistant telemetry performance hook")
