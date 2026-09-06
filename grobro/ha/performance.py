"""Low-risk Home Assistant telemetry hot-path optimizations.

This module deliberately changes no entity, topic, register or control semantics.
It combines repeated passes over one already-decoded telemetry payload into one
pass and normalizes Home Assistant power sensors in watts to whole-watt values.
"""

from __future__ import annotations

import json
import logging
import math

from grobro.ha import client as ha_client_module

LOG = logging.getLogger(__name__)
_INSTALLED = False
_REGISTER_RULES_CACHE: dict[
    int,
    tuple[dict, frozenset[str], frozenset[str], frozenset[str], bool],
] = {}
_BAT_SERIAL_GROUPS = (
    (2, ("bat2_ser_part_1", "bat2_ser_part_2", "bat2_ser_part_3", "bat2_ser_part_4"), "bat2_serial"),
    (3, ("bat3_ser_part_1", "bat3_ser_part_2", "bat3_ser_part_3", "bat3_ser_part_4"), "bat3_serial"),
    (4, ("bat4_ser_part_1", "bat4_ser_part_2", "bat4_ser_part_3", "bat4_ser_part_4"), "bat4_serial"),
)


def _register_rules(known_registers):
    """Cache static per-register HA rules for one immutable runtime register map."""
    if known_registers is None:
        return {}, frozenset(), frozenset(), frozenset(), False

    cache_key = id(known_registers)
    cached = _REGISTER_RULES_CACHE.get(cache_key)
    if cached is not None:
        return cached

    enum_registers: dict = {}
    total_increasing: set[str] = set()
    invalid_battery_temps: set[str] = set()
    whole_watt_power: set[str] = set()
    has_battery_serial_parts = False

    for name, reg in known_registers.input_registers.items():
        data = getattr(reg.growatt, "data", None)
        if data is not None and getattr(data, "data_type", None) == "ENUM":
            enum_registers[name] = reg
        ha_reg = reg.homeassistant
        if getattr(ha_reg, "state_class", None) == "total_increasing":
            total_increasing.add(name)
        if (
            getattr(ha_reg, "device_class", None) == "power"
            and getattr(ha_reg, "unit_of_measurement", None) == "W"
        ):
            whole_watt_power.add(name)
        if name.startswith("bat") and name.endswith("_temp"):
            invalid_battery_temps.add(name)
        if name.startswith("bat") and "_ser_part_" in name:
            has_battery_serial_parts = True

    rules = (
        enum_registers,
        frozenset(total_increasing),
        frozenset(invalid_battery_temps),
        frozenset(whole_watt_power),
        has_battery_serial_parts,
    )
    _REGISTER_RULES_CACHE[cache_key] = rules
    return rules


def _prepare_payload(
    client,
    state,
    effective_max_bat: int,
    known_registers,
    rules=None,
):
    """Apply the existing HA value rules in one pass over the source payload."""
    if rules is None:
        rules = _register_rules(known_registers)
    (
        enum_registers,
        total_increasing,
        invalid_battery_temps,
        whole_watt_power,
        _,
    ) = rules

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
        if (
            isinstance(value, (int, float))
            and value == -273.1
            and key in invalid_battery_temps
        ):
            value = None

        enum_reg = enum_registers.get(key)
        if enum_reg is not None:
            value = map_enum_value(enum_reg, value)

        if (
            filter_data_glitches
            and key in total_increasing
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

        # Home Assistant power values in watts are intentionally published as
        # whole numbers. This removes meaningless sub-watt display noise and,
        # importantly, prevents negative zero (for example -0.4 W -> 0 W).
        # Other measurements, including Wh/kWh energy counters, are untouched.
        if (
            key in whole_watt_power
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        ):
            value = int(round(value))

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
        rules = _register_rules(known_registers)
        payload = _prepare_payload(
            self,
            state,
            effective_max_bat,
            known_registers,
            rules,
        )

        # Only families whose static register map contains serial parts need the
        # legacy combine step. The key strings themselves are prebuilt as well.
        if rules[4]:
            for _bat_num, part_keys, combined_key in _BAT_SERIAL_GROUPS:
                parts = []
                for key in part_keys:
                    value = payload.pop(key, None)
                    if value is not None:
                        parts.append(str(value))
                combined = "".join(parts).strip()
                if combined:
                    payload[combined_key] = combined
                else:
                    payload.pop(combined_key, None)

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
