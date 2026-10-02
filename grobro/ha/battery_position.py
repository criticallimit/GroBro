"""Persistent NOAH battery-slot stabilization for Home Assistant."""

from __future__ import annotations

import json
import logging
import os
import re
from threading import RLock

LOG = logging.getLogger(__name__)

_POSITION_FILE = "battery_positions.json"
_MANUAL_POSITION_FILE = "battery_manual_positions.json"
_DETECTED_FILE = "battery_detected.json"
_PERSISTENCE_LOCK = RLock()
_TRACKED_SLOTS = (2, 3, 4)
AUTO_ASSIGNMENT = "__auto__"
EMPTY_ASSIGNMENT = "__empty__"
_BAT_KEY_PATTERNS = (
    re.compile(r"^bat([234])(?=_)"),
    re.compile(r"^bat_([234])(?=_)"),
    re.compile(r"^battery([234])(?=[A-Z_])"),
    re.compile(r"^(?:maxcvbat|mincvbat)([234])(?=$|_)"),
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
        keys = tuple(f"bat{slot}_ser_part_{index}" for index in range(1, 5))
        parts = [
            _clean_serial_part(payload.get(key)) for key in keys
        ]
        # Wire fragments are four bytes each. Also accept the established API
        # representation that places a complete serial in the first field.
        complete_serial = len(parts[0]) > 4 and not any(parts[1:])
        if not complete_serial and any(key not in payload or payload[key] is None for key in keys):
            continue
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
    _save_json_atomic(positions, path)


def _load_manual_positions(
    path: str = _MANUAL_POSITION_FILE,
) -> dict[str, dict[int, str]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        LOG.warning("Failed to load manual battery position map %s: %s", path, exc)
        return {}

    result: dict[str, dict[int, str]] = {}
    if not isinstance(raw, dict):
        return result

    for device_id, assignments in raw.items():
        if not isinstance(assignments, dict):
            continue
        clean: dict[int, str] = {}
        explicit_serials: set[str] = set()
        valid = True
        for slot in _TRACKED_SLOTS:
            value = assignments.get(str(slot), AUTO_ASSIGNMENT)
            value = str(value).strip()
            if value in {AUTO_ASSIGNMENT, EMPTY_ASSIGNMENT}:
                clean[slot] = value
                continue
            if not _is_plausible_serial(value) or value in explicit_serials:
                valid = False
                break
            explicit_serials.add(value)
            clean[slot] = value
        if valid:
            result[str(device_id)] = clean
    return result


def _save_manual_positions(
    positions: dict[str, dict[int, str]],
    path: str = _MANUAL_POSITION_FILE,
) -> None:
    serializable = {
        device_id: {str(slot): value for slot, value in assignments.items()}
        for device_id, assignments in positions.items()
    }
    _save_json_atomic(serializable, path)


def _save_json_atomic(payload: object, path: str) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
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


def _manual_positions(client) -> dict[str, dict[int, str]]:
    try:
        mtime = os.stat(_MANUAL_POSITION_FILE).st_mtime_ns
    except FileNotFoundError:
        mtime = None
    except OSError:
        mtime = None

    cached_mtime = getattr(client, "_battery_manual_position_mtime", object())
    positions = getattr(client, "_battery_manual_position_maps", None)
    if positions is None or cached_mtime != mtime:
        positions = _load_manual_positions()
        client._battery_manual_position_maps = positions
        client._battery_manual_position_mtime = mtime
    return positions


def _record_detected_serials(client, device_id: str, serials: dict[int, str]) -> None:
    if not serials:
        return

    entries = [
        {"physical_slot": slot, "serial": serial}
        for slot, serial in sorted(serials.items())
    ]
    cache = getattr(client, "_battery_detected_serials", None)
    if cache is None:
        try:
            with open(_DETECTED_FILE, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            cache = raw if isinstance(raw, dict) else {}
        except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
            cache = {}
        client._battery_detected_serials = cache

    if cache.get(device_id) == entries:
        return
    cache[device_id] = entries
    _save_json_atomic(cache, _DETECTED_FILE)


def _load_detected_serials(path: str = _DETECTED_FILE) -> dict[str, list[dict]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}

    result: dict[str, list[dict]] = {}
    for device_id, entries in raw.items():
        if not isinstance(entries, list):
            continue
        clean_entries = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            serial = _clean_serial_part(entry.get("serial"))
            try:
                physical_slot = int(entry.get("physical_slot"))
            except (TypeError, ValueError):
                continue
            if (
                _is_plausible_serial(serial)
                and physical_slot in _TRACKED_SLOTS
                and serial not in seen
            ):
                clean_entries.append(
                    {"physical_slot": physical_slot, "serial": serial}
                )
                seen.add(serial)
        if clean_entries:
            result[str(device_id)] = clean_entries
    return result


def save_manual_assignments(device_id: str, assignments: dict) -> None:
    """Validate and persist the three manual logical-slot selections."""
    with _PERSISTENCE_LOCK:
        _save_manual_assignments_locked(device_id, assignments)


def _save_manual_assignments_locked(device_id: str, assignments: dict) -> None:
    device_id = str(device_id).strip()
    if not device_id:
        raise ValueError("device_id is required")

    clean: dict[int, str] = {}
    explicit_serials: set[str] = set()
    for slot in _TRACKED_SLOTS:
        value = str(assignments.get(str(slot), AUTO_ASSIGNMENT)).strip()
        if value in {AUTO_ASSIGNMENT, EMPTY_ASSIGNMENT}:
            clean[slot] = value
            continue
        if not _is_plausible_serial(value) or value in explicit_serials:
            raise ValueError("invalid or duplicate battery serial")
        explicit_serials.add(value)
        clean[slot] = value

    all_manual = _load_manual_positions()
    if all(value == AUTO_ASSIGNMENT for value in clean.values()):
        all_manual.pop(device_id, None)
    else:
        all_manual[device_id] = clean
    _save_manual_positions(all_manual)


def load_battery_ui_state() -> dict:
    """Return persisted automatic/manual mappings and last detected serials."""
    with _PERSISTENCE_LOCK:
        return _load_battery_ui_state_locked()


def _load_battery_ui_state_locked() -> dict:
    automatic = _load_all_positions()
    manual = _load_manual_positions()
    detected = _load_detected_serials()
    device_ids = sorted(set(automatic) | set(manual) | set(detected))
    devices = []

    for device_id in device_ids:
        automatic_by_slot = {
            str(slot): serial
            for serial, slot in automatic.get(device_id, {}).items()
        }
        manual_by_slot = {
            str(slot): manual.get(device_id, {}).get(slot, AUTO_ASSIGNMENT)
            for slot in _TRACKED_SLOTS
        }
        devices.append(
            {
                "device_id": device_id,
                "detected": detected.get(device_id, []),
                "automatic": automatic_by_slot,
                "manual": manual_by_slot,
            }
        )

    return {
        "keep_battery_position": os.getenv(
            "KEEP_BATTERY_POSITION",
            "False",
        ).lower()
        == "true",
        "devices": devices,
    }


def _position_maps(client) -> dict[str, dict[str, int]]:
    positions = getattr(client, "_battery_position_maps", None)
    if positions is None:
        positions = _load_all_positions()
        client._battery_position_maps = positions
    return positions


def observe_battery_serials(client, device_id: str, payload: dict) -> None:
    """Persist the currently detected battery serials for the Ingress UI."""
    with _PERSISTENCE_LOCK:
        _record_detected_serials(client, device_id, _serials_from_payload(payload))


def has_manual_assignments(client, device_id: str) -> bool:
    """Return whether at least one slot has a non-automatic manual choice."""
    with _PERSISTENCE_LOCK:
        assignments = _manual_positions(client).get(device_id, {})
        return any(value != AUTO_ASSIGNMENT for value in assignments.values())


def _stabilize_battery_payload_locked(
    client,
    device_id: str,
    payload: dict,
    *,
    use_stable_auto: bool = True,
) -> tuple[dict, int]:
    """Return payload remapped to stable logical battery slots.

    The first observed serial/slot relationship becomes persistent. If NOAH later
    re-enumerates the physical chain after one pack disappears, every slot-specific
    value is moved back to the logical slot belonging to that serial number.

    Returns the remapped payload and the highest logical slot currently present.
    """
    current_serials = _serials_from_payload(payload)
    _record_detected_serials(client, device_id, current_serials)
    manual_assignments = _manual_positions(client).get(device_id, {})

    # Initialize the per-client persistent map even when the current packet does
    # not contain a valid serial. This keeps runtime state deterministic without
    # creating any slot assignment from invalid/noisy serial fragments.
    all_positions = _position_maps(client)
    if not current_serials and not manual_assignments:
        return payload, 1

    mapping = all_positions.setdefault(device_id, {})
    changed = False

    if use_stable_auto:
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
    explicit_slot_by_serial = {
        value: slot
        for slot, value in manual_assignments.items()
        if value not in {AUTO_ASSIGNMENT, EMPTY_ASSIGNMENT}
    }
    reserved_manual_slots = {
        slot
        for slot, value in manual_assignments.items()
        if value != AUTO_ASSIGNMENT
    }
    used_slots: set[int] = set()

    # Explicit serial selections always win.
    for physical_slot, serial in current_serials.items():
        logical_slot = explicit_slot_by_serial.get(serial)
        if logical_slot is None:
            continue
        physical_to_logical[physical_slot] = logical_slot
        used_slots.add(logical_slot)

    # Remaining batteries keep their automatic stable slot whenever that slot
    # is not reserved manually. Otherwise choose an unreserved automatic slot.
    for physical_slot, serial in current_serials.items():
        if physical_slot in physical_to_logical:
            continue

        logical_slot = mapping.get(serial) if use_stable_auto else physical_slot
        if (
            logical_slot in reserved_manual_slots
            or logical_slot in used_slots
        ):
            logical_slot = None

        if logical_slot is None:
            candidates = (
                [physical_slot]
                if physical_slot in _TRACKED_SLOTS
                else []
            ) + list(_TRACKED_SLOTS)
            logical_slot = next(
                (
                    slot
                    for slot in candidates
                    if slot not in reserved_manual_slots
                    and slot not in used_slots
                ),
                None,
            )

        if logical_slot is None:
            LOG.warning(
                "No free logical battery slot for %s on device %s",
                serial,
                device_id,
            )
            continue

        physical_to_logical[physical_slot] = logical_slot
        used_slots.add(logical_slot)
        if physical_slot != logical_slot:
            if use_stable_auto and serial not in explicit_slot_by_serial:
                message = (
                    "Battery %s reported as Bat%d but kept at stable Bat%d "
                    "for device %s"
                )
            else:
                message = (
                    "Battery %s reported as Bat%d but manually kept at Bat%d "
                    "for device %s"
                )
            LOG.debug(
                message,
                serial,
                physical_slot,
                logical_slot,
                device_id,
            )

    if not reserved_manual_slots and all(
        physical_to_logical.get(slot, slot) == slot
        for slot in physical_to_logical
    ) and len(physical_to_logical) == len(current_serials):
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
        # An identified pack owns its logical destination. Unidentified/empty
        # physical slots must not overwrite it, nor populate reserved slots.
        if physical_slot not in physical_to_logical and (
            physical_slot in used_slots
            or physical_slot in reserved_manual_slots
            or physical_slot in current_serials
        ):
            continue
        logical_slot = physical_to_logical.get(physical_slot, physical_slot)
        remapped[_remap_key(key, logical_slot)] = value

    return remapped, max(physical_to_logical.values(), default=1)

def stabilize_battery_payload(
    client,
    device_id: str,
    payload: dict,
    *,
    use_stable_auto: bool = True,
) -> tuple[dict, int]:
    """Thread-safe wrapper for stable/manual battery slot remapping."""
    with _PERSISTENCE_LOCK:
        return _stabilize_battery_payload_locked(
            client,
            device_id,
            payload,
            use_stable_auto=use_stable_auto,
        )
