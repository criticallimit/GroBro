"""Persistent NOAH battery-slot stabilization for Home Assistant."""

from __future__ import annotations

import json
import logging
import os
import re

LOG = logging.getLogger(__name__)

_POSITION_FILE = "battery_positions.json"
_TRACKED_SLOTS = (2, 3, 4)
_BAT_KEY_PATTERNS = (
    re.compile(r"^bat([234])(?=_)"),
    re.compile(r"^bat_([234])(?=_)"),
    re.compile(r"^battery([234])(?=[A-Z_])"),
)


def _clean_serial_part(value) -> str:
    if value is None:
        return ""
    return str(value).strip().strip("\x00").strip()


def _is_plausible_serial(value: str) -> bool:
    """Reject empty/noisy register data before it can define a stable slot."""
    if not (8 <= len(value) <= 40):
        return False
    return all(char.isalnum() or char in "._-" for char in value)


def _serials_from_payload(payload: dict) -> dict[int, str]:
    """Build the currently reported serial number for physical slots 2..4."""
    serials: dict[int, str] = {}
    for slot in _TRACKED_SLOTS:
        parts = [
            _clean_serial_part(payload.get(f"bat{slot}_ser_part_{index}"))
            for index in range(1, 5)
        ]
        serial = "".join(part for part in parts if part).strip()
        if _is_plausible_serial(serial):
            serials[slot] = serial
    return serials


def _logical_slot_from_key(name: str) -> int | None:
    for pattern in _BAT_KEY_PATTERNS:
        match = pattern.match(name)
        if match:
            return int(match.group(1))
    return None


def _remap_key(name: str, logical_slot: int) -> str:
    for pattern in _BAT_KEY_PATTERNS:
        match = pattern.match(name)
        if match:
            start, end = match.span(1)
            return f"{name[:start]}{logical_slot}{name[end:]}"
    return name


def _load_all_positions(path: str = _POSITION_FILE) -> dict[str, dict[str, int]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        LOG.warning("Failed to load battery position map %s: %s", path, exc)
        return {}

    result: dict[str, dict[str, int]] = {}
    if not isinstance(raw, dict):
        return result
    for device_id, mapping in raw.items():
        if not isinstance(mapping, dict):
            continue
        clean: dict[str, int] = {}
        used_slots: set[int] = set()
        for serial, slot in mapping.items():
            try:
                slot_number = int(slot)
            except (TypeError, ValueError):
                continue
            serial_text = _clean_serial_part(serial)
            if (
                serial_text
                and slot_number in _TRACKED_SLOTS
                and slot_number not in used_slots
            ):
                clean[serial_text] = slot_number
                used_slots.add(slot_number)
        if clean:
            result[str(device_id)] = clean
    return result


def _save_all_positions(
    positions: dict[str, dict[str, int]],
    path: str = _POSITION_FILE,
) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(positions, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        os.replace(temp_path, path)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


def _position_maps(client) -> dict[str, dict[str, int]]:
    positions = getattr(client, "_battery_position_maps", None)
    if positions is None:
        positions = _load_all_positions()
        client._battery_position_maps = positions
    return positions


def stabilize_battery_payload(client, device_id: str, payload: dict) -> tuple[dict, int]:
    """Return payload remapped to stable logical battery slots.

    The first observed serial/slot relationship becomes persistent. If NOAH later
    re-enumerates the physical chain after one pack disappears, every slot-specific
    value is moved back to the logical slot belonging to that serial number.

    Returns the remapped payload and the highest logical slot currently present.
    """
    current_serials = _serials_from_payload(payload)
    # Initialize the per-client persistent map even when the current packet does
    # not contain a valid serial. This keeps runtime state deterministic without
    # creating any slot assignment from invalid/noisy serial fragments.
    all_positions = _position_maps(client)
    if not current_serials:
        return payload, 1

    mapping = all_positions.setdefault(device_id, {})
    changed = False

    # Existing serial assignments reserve their logical slots even while the
    # battery is temporarily absent. New batteries therefore cannot steal them.
    reserved_slots = set(mapping.values())

    for physical_slot, serial in current_serials.items():
        if serial in mapping:
            continue

        if physical_slot in _TRACKED_SLOTS and physical_slot not in reserved_slots:
            logical_slot = physical_slot
        else:
            logical_slot = next(
                (slot for slot in _TRACKED_SLOTS if slot not in reserved_slots),
                None,
            )
        if logical_slot is None:
            LOG.warning(
                "No free stable battery slot for %s on device %s",
                serial,
                device_id,
            )
            continue

        mapping[serial] = logical_slot
        reserved_slots.add(logical_slot)
        changed = True
        LOG.info(
            "Assigned battery %s to stable Bat%d for device %s",
            serial,
            logical_slot,
            device_id,
        )

    if changed:
        _save_all_positions(all_positions)

    physical_to_logical: dict[int, int] = {}
    for physical_slot, serial in current_serials.items():
        logical_slot = mapping.get(serial)
        if logical_slot is None:
            continue
        physical_to_logical[physical_slot] = logical_slot
        if physical_slot != logical_slot:
            LOG.warning(
                "Battery %s reported as Bat%d but kept at stable Bat%d for device %s",
                serial,
                physical_slot,
                logical_slot,
                device_id,
            )

    if all(
        physical_to_logical.get(slot, slot) == slot
        for slot in physical_to_logical
    ):
        return payload, max(physical_to_logical.values(), default=1)

    remapped: dict = {}
    slot_items: list[tuple[str, object, int]] = []
    for key, value in payload.items():
        slot = _logical_slot_from_key(key)
        if slot is None:
            remapped[key] = value
        else:
            slot_items.append((key, value, slot))

    for key, value, physical_slot in slot_items:
        logical_slot = physical_to_logical.get(physical_slot, physical_slot)
        remapped[_remap_key(key, logical_slot)] = value

    return remapped, max(physical_to_logical.values(), default=1)
