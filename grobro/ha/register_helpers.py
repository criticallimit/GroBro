"""Shared register naming and command-definition traversal."""
from typing import Optional

from grobro.model.growatt_registers import GroBroRegisters


def _get_bat_number(name: str) -> Optional[int]:
    if name.startswith("battery"):
        rest = name[7:]
        digits = ""
        for c in rest:
            if c.isdigit():
                digits += c
            else:
                break
        if digits:
            return int(digits)
    elif name.startswith("bat"):
        rest = name[3:]
        if rest.startswith("_"):
            rest = rest[1:]
        digits = ""
        for c in rest:
            if c.isdigit():
                digits += c
            else:
                break
        if digits:
            return int(digits)
    elif name.startswith(("maxcvbat", "mincvbat")):
        prefix = "maxcvbat" if name.startswith("maxcvbat") else "mincvbat"
        rest = name[len(prefix):]
        digits = ""
        for c in rest:
            if c.isdigit():
                digits += c
            else:
                break
        if digits:
            return int(digits)
    return None


def iter_command_registers(known_registers: GroBroRegisters):
    # Modbus holding registers
    for name, reg in known_registers.holding_registers.items():
        yield {
            "name": name,
            "ha": reg.homeassistant,
            "topic_root": reg.homeassistant.type,
            "cmd_id": name,
            "state_id": name,
            "is_config": False,
        }

    # Config registers
    for name, reg in known_registers.config_registers.items():
        yield {
            "name": name,
            "ha": reg.homeassistant,
            "topic_root": "config",
            "cmd_id": str(reg.growatt.register_no),
            "state_id": str(reg.growatt.register_no),
            "is_config": True,
        }
