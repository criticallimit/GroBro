"""Build HA discovery data without MQTT, storage or runtime cache access."""
from grobro import model
from grobro.ha.register_helpers import _get_bat_number, iter_command_registers


_REDUNDANT_DEFAULT_ICONS = {
    ("battery", "mdi:battery"),
    ("temperature", "mdi:thermometer"),
    ("current", "mdi:current-ac"),
    ("frequency", "mdi:sine-wave"),
    ("signal_strength", "mdi:wifi"),
    ("voltage", "mdi:flash"),
    ("voltage", "mdi:sine-wave"),
    ("power", "mdi:flash"),
}


def _uses_redundant_default_icon(device_class, icon):
    return (device_class, icon) in _REDUNDANT_DEFAULT_ICONS


def build_discovery_payload(
    device_id, known_registers, device_info, *, base_topic, bridge_topic,
    effective_max_bat, pv_count, max_slots, device_timeout, availability_sensor,
):
    # prepare discovery payload
    payload: dict = {
        "dev": device_info,
        "availability": [
            {"topic": f"{base_topic}/grobro/{device_id}/availability"},
            {"topic": bridge_topic},
        ],
        "availability_mode": "all",
        "o": {"name": "grobro", "url": "https://github.com/robertzaage/GroBro"},
        "cmps": {},
    }

    # Commands (Modbus + Config)
    for entry in iter_command_registers(known_registers):
        ha = entry["ha"]
        if not ha.publish:
            continue

        # slot filtering applies only to modbus
        if not entry["is_config"] and entry["name"].startswith("slot"):
            try:
                if int(entry["name"][4]) > max_slots:
                    continue
            except ValueError:
                continue

        unique_id = f"grobro_{device_id}_cmd_{entry['name']}"
        platform = ha.type

        ha_data = ha.model_dump(exclude_none=True)
        if _uses_redundant_default_icon(ha.device_class, ha.icon):
            ha_data.pop("icon", None)

        # Home Assistant erwartet bei Select eine Liste, kein Dict
        if platform == "select":
            options = ha_data.get("options")
            if isinstance(options, dict):
                ha_data["options"] = list(options.values())

        component = {
            "platform": platform,
            "name": ha.name,
            "unique_id": unique_id,
            "state_topic": (
                f"{base_topic}/{entry['topic_root']}/grobro/"
                f"{device_id}/{entry['state_id']}/get"
            ),
            **ha_data,
        }
        if platform != "sensor":
            component["command_topic"] = (
                f"{base_topic}/{entry['topic_root']}/grobro/"
                f"{device_id}/{entry['cmd_id']}/set"
            )
        payload["cmps"][unique_id] = component
    # Config command: Restart Datalogger (Register 32 / Value 1)
    restart_uid = f"grobro_{device_id}_restart_datalogger"
    payload["cmps"][restart_uid] = {
        "platform": "button",
        "name": "Restart Datalogger",
        "command_topic": f"{base_topic}/config/grobro/{device_id}/32/set",
        "payload_press": "1",
        "icon": "mdi:restart",
        "unique_id": restart_uid
    }

    # Config command: Sync Time (register 31 / Value "%Y-%m-%d %H:%M:%S")
    time_sync_uid = f"grobro_{device_id}_sync_time"
    payload["cmps"][time_sync_uid] = {
        "platform": "button",
        "name": "Sync Time",
        "icon": "mdi:clock-outline",
        "command_topic": f"{base_topic}/config/grobro/{device_id}/31/set",
        "unique_id": time_sync_uid
    }

    # Read-All Button
    payload["cmps"][f"grobro_{device_id}_cmd_read_all"] = {
        "command_topic": f"{base_topic}/button/grobro/{device_id}/read_all/read",
        "platform": "button",
        "unique_id": f"grobro_{device_id}_cmd_read_all",
        "name": "Read All Values",
    }

    # States
    for state_name, state in known_registers.input_registers.items():
        if not state.homeassistant.publish:
            if not (pv_count == 4 and state_name in ("Vpv3", "Ipv3", "Ppv3", "Vpv4", "Ipv4", "Ppv4", "Epv3_today", "Epv3_total")):
                continue
        bat_num = _get_bat_number(state_name)
        if bat_num is not None and bat_num > effective_max_bat:
            continue
        if "_ser_part_" in state_name and state_name.startswith("bat"):
            continue
        unique_id = f"grobro_{device_id}_{state_name}"
        component = {
            "platform": "sensor",
            "name": state.homeassistant.name,
            "state_topic": f"{base_topic}/grobro/{device_id}/state",
            "value_template": f"{{{{ value_json['{state_name}'] }}}}",
            "unique_id": unique_id,
            "device_class": state.homeassistant.device_class,
            "state_class": state.homeassistant.state_class,
            "unit_of_measurement": state.homeassistant.unit_of_measurement,
            **(
                {
                    "suggested_display_precision":
                    state.homeassistant.suggested_display_precision
                }
                if state.homeassistant.suggested_display_precision is not None
                else {}
            ),
        }
        # Prefer Home Assistant's device-class icon where our configured icon
        # only duplicates the native default. Keep semantic icons such as
        # solar-power, power-plug, battery-sync and other explicit UI hints.
        if not _uses_redundant_default_icon(
            state.homeassistant.device_class,
            state.homeassistant.icon,
        ):
            component["icon"] = state.homeassistant.icon
        payload["cmps"][unique_id] = component

    # Combined battery serial entities remain a NOAH-only UI feature.
    # NEXA serial fragments are decoded internally for stable slot mapping.
    has_bat_ser_parts = (
        model.is_family(device_id, "noah")
        and any(
            name.startswith("bat") and "_ser_part_" in name
            for name in known_registers.input_registers
        )
    )
    if has_bat_ser_parts:
        for bat_num in range(2, 5):
            if bat_num > effective_max_bat:
                continue
            combined_name = f"bat{bat_num}_serial"
            uid = f"grobro_{device_id}_{combined_name}"
            payload["cmps"][uid] = {
                "platform": "sensor",
                "name": f"Bat{bat_num} Serial",
                "state_topic": f"{base_topic}/grobro/{device_id}/state",
                "value_template": f"{{{{ value_json['{combined_name}'] }}}}",
                "unique_id": uid,
                "icon": "mdi:identifier",
            }

    # Combined firmware version (NOAH = 3 parts, NEXA = 4 parts)
    fw_version_parts = sorted(
        name
        for name in known_registers.input_registers
        if name.startswith("fw_version_part_")
    )

    if fw_version_parts:
        combined_name = "fw_version"
        firmware_unique_id = f"grobro_{device_id}_{combined_name}"

        value_template = ".".join(
            f"{{{{ value_json['{part}'] }}}}"
            for part in fw_version_parts
        )

        payload["cmps"][firmware_unique_id] = {
            "platform": "sensor",
            "name": "Firmware Version",
            "state_topic": f"{base_topic}/grobro/{device_id}/state",
            "value_template": value_template,
            "unique_id": firmware_unique_id,
            "icon": "mdi:information",
        }

    # Serial Number Entity
    serial_unique_id = f"grobro_{device_id}_serial"
    payload["cmps"][serial_unique_id] = {
        "platform": "sensor",
        "name": "Device SN",
        "state_topic": f"{base_topic}/grobro/{device_id}/serial",
        "unique_id": serial_unique_id,
        "icon": "mdi:identifier",
    }

    # Device Type Entity
    type_unique_id = f"grobro_{device_id}_type"
    payload["cmps"][type_unique_id] = {
        "platform": "sensor",
        "name": "Device Type",
        "state_topic": f"{base_topic}/grobro/{device_id}/type",
        "unique_id": type_unique_id,
        "icon": "mdi:chip",
    }

    # Online Entity
    if device_timeout > 0 and availability_sensor:
        online_unique_id = f"grobro_{device_id}_online"
        payload["cmps"][online_unique_id] = {
            "platform": "binary_sensor",
            "name": "Online",
            "state_topic": f"{base_topic}/grobro/{device_id}/online",
            "device_class": "connectivity",
            "unique_id": online_unique_id,
        }

    return payload
