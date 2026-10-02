"""Supervisor-backed Better GroBro add-on configuration."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta
import urllib.error
import urllib.request

_SUPERVISOR_BASE = "http://supervisor"
_PROCESS_LOG_MARKER = f"BETTER_GROBRO_SESSION_{uuid.uuid4().hex}"
_PROCESS_STARTED_AT = datetime.now().astimezone().isoformat(timespec="seconds")
_ALLOWED_OPTIONS = {
    "SOURCE_MQTT_HOST",
    "SOURCE_MQTT_PORT",
    "SOURCE_MQTT_TLS",
    "SOURCE_MQTT_USER",
    "SOURCE_MQTT_PASS",
    "TARGET_MQTT_HOST",
    "TARGET_MQTT_PORT",
    "TARGET_MQTT_TLS",
    "TARGET_MQTT_USER",
    "TARGET_MQTT_PASS",
    "MQTT_CLIENT_SUFFIX",
    "HA_BASE_TOPIC",
    "GROWATT_CLOUD",
    "GROWATT_CLOUD_CONFIG_FILTER",
    "LOG_LEVEL",
    "DUMP_MESSAGES",
    "DUMP_DIR",
    "REGISTER_DEBUG",
    "REGISTER_DEBUG_DIR",
    "REGISTER_DEBUG_MAX_REGISTER",
    "REGISTER_DEBUG_CHANGES_ONLY",
    "DEVICE_TIMEOUT",
    "MAX_SLOTS",
    "MAX_BAT",
    "AVAILABILITY_SENSOR",
    "TZ",
    "KEEP_BATTERY_POSITION",
}
_RETIRED_OPTIONS = {"PUBLISH_SENSORS_RETAINED", "FILTER_DATA_GLITCHES"}
_DEFAULTS = {
    "SOURCE_MQTT_HOST": "homeassistant.local",
    "SOURCE_MQTT_PORT": 7006,
    "SOURCE_MQTT_TLS": True,
    "SOURCE_MQTT_USER": "",
    "SOURCE_MQTT_PASS": "",
    "TARGET_MQTT_HOST": "homeassistant.local",
    "TARGET_MQTT_PORT": 1883,
    "TARGET_MQTT_TLS": False,
    "TARGET_MQTT_USER": "",
    "TARGET_MQTT_PASS": "",
    "MQTT_CLIENT_SUFFIX": "",
    "HA_BASE_TOPIC": "homeassistant",
    "GROWATT_CLOUD": False,
    "GROWATT_CLOUD_CONFIG_FILTER": False,
    "LOG_LEVEL": "ERROR",
    "DUMP_MESSAGES": False,
    "DUMP_DIR": "/share/GroBro/dump",
    "REGISTER_DEBUG": False,
    "REGISTER_DEBUG_DIR": "/share/GroBro/register_debug",
    "REGISTER_DEBUG_MAX_REGISTER": 65535,
    "REGISTER_DEBUG_CHANGES_ONLY": True,
    "DEVICE_TIMEOUT": 120,
    "MAX_SLOTS": 1,
    "MAX_BAT": "auto",
    "AVAILABILITY_SENSOR": False,
    "TZ": "",
    "KEEP_BATTERY_POSITION": False,
}
_BOOL_OPTIONS = {
    key for key, value in _DEFAULTS.items() if isinstance(value, bool)
}
_INT_OPTIONS = {
    "SOURCE_MQTT_PORT",
    "TARGET_MQTT_PORT",
    "REGISTER_DEBUG_MAX_REGISTER",
    "DEVICE_TIMEOUT",
    "MAX_SLOTS",
}


class SupervisorConfigError(RuntimeError):
    """Raised when the Supervisor rejects or cannot process configuration."""


def _token() -> str:
    token = os.getenv("SUPERVISOR_TOKEN", "").strip()
    if not token:
        raise SupervisorConfigError("SUPERVISOR_TOKEN ist nicht verfügbar")
    return token


def _unwrap(payload):
    if isinstance(payload, dict) and payload.get("result") in {"ok", "error"}:
        if payload.get("result") == "error":
            raise SupervisorConfigError(str(payload.get("message", "Supervisor-Fehler")))
        return payload.get("data")
    return payload


def _supervisor_request(method: str, path: str, payload=None):
    body = None
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{_SUPERVISOR_BASE}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode())
            message = detail.get("message") or detail.get("error") or str(detail)
        except Exception:
            message = str(exc)
        raise SupervisorConfigError(message) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise SupervisorConfigError(str(exc)) from exc

    if not raw:
        return None
    try:
        return _unwrap(json.loads(raw))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SupervisorConfigError("Ungültige Supervisor-Antwort") from exc


def mark_process_log_start() -> None:
    """Write a unique marker used to isolate the current process log session."""
    print(f"--- {_PROCESS_LOG_MARKER} ---", flush=True)


def _supervisor_text_request(path: str) -> str:
    """Fetch plain-text data from Supervisor endpoints such as add-on logs."""
    request = urllib.request.Request(
        f"{_SUPERVISOR_BASE}{path}",
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "text/plain",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise SupervisorConfigError(str(exc)) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise SupervisorConfigError(str(exc)) from exc


def _logs_since_process_start(raw: str) -> str:
    """Fallback session slicing when the explicit marker is not in Supervisor logs."""
    try:
        started = datetime.fromisoformat(_PROCESS_STARTED_AT)
    except ValueError:
        return ""

    # Logging timestamps have millisecond precision but no timezone suffix.
    # Compare them in the process-local timezone and allow a small bootstrap
    # tolerance so the very first startup messages are not lost.
    threshold = started - timedelta(seconds=2)
    lines = raw.splitlines()
    for index, line in enumerate(lines):
        stamp = line[:23]
        try:
            line_time = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S,%f")
        except ValueError:
            continue
        line_time = line_time.replace(tzinfo=started.tzinfo)
        if line_time >= threshold:
            return "\n".join(lines[index:])
    return ""


def get_current_process_logs() -> dict:
    """Return only log output produced by the current Better GroBro process."""
    raw = _supervisor_text_request("/addons/self/logs")
    marker = f"--- {_PROCESS_LOG_MARKER} ---"
    position = raw.rfind(marker)
    if position >= 0:
        logs = raw[position + len(marker):].lstrip("\r\n")
        return {
            "logs": logs,
            "started_at": _PROCESS_STARTED_AT,
            "marker_found": True,
        }

    # Some Supervisor/container startup paths do not retain the early stdout
    # marker. Fall back to the process start timestamp instead of leaving the
    # integrated viewer waiting forever.
    logs = _logs_since_process_start(raw)
    return {
        "logs": logs,
        "started_at": _PROCESS_STARTED_AT,
        "marker_found": bool(logs),
    }


def normalize_options(raw: dict) -> dict:
    """Validate and normalize options accepted from the Ingress browser."""
    if not isinstance(raw, dict):
        raise SupervisorConfigError("Ungültige Optionen")

    result = {}
    for key, value in raw.items():
        if key not in _ALLOWED_OPTIONS:
            continue

        if key in _BOOL_OPTIONS:
            if not isinstance(value, bool):
                raise SupervisorConfigError(f"{key}: boolescher Wert erwartet")
            result[key] = value
            continue

        if key in _INT_OPTIONS:
            if isinstance(value, bool):
                raise SupervisorConfigError(f"{key}: Zahl erwartet")
            try:
                number = int(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise SupervisorConfigError(f"{key}: ungültige Zahl") from exc
            if isinstance(value, float) and value != number:
                raise SupervisorConfigError(f"{key}: ungültige Zahl")
            if key in {"SOURCE_MQTT_PORT", "TARGET_MQTT_PORT"} and not 1 <= number <= 65535:
                raise SupervisorConfigError(f"{key}: Port muss zwischen 1 und 65535 liegen")
            if key == "REGISTER_DEBUG_MAX_REGISTER" and not 0 <= number <= 65535:
                raise SupervisorConfigError(
                    "REGISTER_DEBUG_MAX_REGISTER muss zwischen 0 und 65535 liegen"
                )
            if key == "DEVICE_TIMEOUT" and number < 0:
                raise SupervisorConfigError("DEVICE_TIMEOUT darf nicht negativ sein")
            if key == "MAX_SLOTS" and not 1 <= number <= 9:
                raise SupervisorConfigError("MAX_SLOTS muss zwischen 1 und 9 liegen")
            result[key] = number
            continue

        if isinstance(value, (dict, list)):
            raise SupervisorConfigError(f"{key}: Text erwartet")
        text = "" if value is None else str(value)
        if key not in {"SOURCE_MQTT_PASS", "TARGET_MQTT_PASS"}:
            text = text.strip()
        if key == "LOG_LEVEL":
            text = text.upper()
            if text not in {"ERROR", "INFO", "DEBUG"}:
                raise SupervisorConfigError("LOG_LEVEL ist ungültig")
        if key == "MAX_BAT":
            if text != "auto":
                try:
                    count = int(text)
                except ValueError as exc:
                    raise SupervisorConfigError("MAX_BAT ist ungültig") from exc
                if not 1 <= count <= 4:
                    raise SupervisorConfigError("MAX_BAT muss auto oder 1 bis 4 sein")
                text = str(count)
        result[key] = text
    return result


def get_home_assistant_language(default: str = "en") -> str:
    """Return Home Assistant Core's configured language."""
    try:
        config = _supervisor_request("GET", "/homeassistant/api/config") or {}
    except SupervisorConfigError:
        return default
    if not isinstance(config, dict):
        return default
    language = str(config.get("language") or default).strip().replace("_", "-")
    return language or default


def get_addon_options() -> dict:
    """Return current official Home Assistant add-on options with defaults."""
    info = _supervisor_request("GET", "/addons/self/info") or {}
    raw_options = info.get("options", {}) if isinstance(info, dict) else {}
    options = dict(_DEFAULTS)
    if isinstance(raw_options, dict):
        options.update(
            {
                key: value
                for key, value in raw_options.items()
                if key not in _RETIRED_OPTIONS
            }
        )
    if int(options.get("DEVICE_TIMEOUT", 120) or 0) <= 0:
        options["DEVICE_TIMEOUT"] = 120
    return {
        "options": options,
        "version": info.get("version") if isinstance(info, dict) else None,
        "state": info.get("state") if isinstance(info, dict) else None,
        "language": get_home_assistant_language(),
    }


def save_addon_options(raw_changes: dict) -> dict:
    """Validate and save changes through the Supervisor options API."""
    changes = normalize_options(raw_changes)
    info = _supervisor_request("GET", "/addons/self/info") or {}
    if not isinstance(info, dict):
        raise SupervisorConfigError("Ungültige Supervisor-Antwort")
    current = info.get("options", {})
    if not isinstance(current, dict):
        current = {}

    merged = {
        key: value
        for key, value in current.items()
        if key not in _RETIRED_OPTIONS
    }
    merged.update(changes)

    _supervisor_request(
        "POST",
        "/addons/self/options",
        {"options": merged},
    )
    return merged


def schedule_restart(delay: float = 1.4) -> None:
    """Restart this add-on after the HTTP response has reached the browser."""

    def worker():
        time.sleep(delay)
        try:
            _supervisor_request("POST", "/addons/self/restart", {})
        except SupervisorConfigError:
            # The restart can close the connection/container before a response is
            # observed. There is nothing useful to recover inside the old process.
            pass

    threading.Thread(
        target=worker,
        name="better-grobro-self-restart",
        daemon=True,
    ).start()
