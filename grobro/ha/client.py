from __future__ import annotations

import os
import ssl
import json
import logging
import time
from threading import Timer
from typing import Callable, Optional
from collections import deque

import paho.mqtt.client as mqtt

import grobro.model as model
from grobro.model.growatt_registers import (
    HomeAssistantInputRegister,
    HomeAssistantHoldingRegisterInput,
    GroBroRegisters,
)
from grobro.model.modbus_message import GrowattModbusFunction
from grobro.model.modbus_function import (
    GrowattModbusFunctionSingle,
)
from grobro.ha.localization import runtime_language
from grobro.model.mqtt_config import publish_succeeded
from grobro.ha.timer_runtime import runtime_lock, guard_runtime

HA_BASE_TOPIC = os.getenv("HA_BASE_TOPIC", "homeassistant")
AVAILABILITY_SENSOR = os.getenv("AVAILABILITY_SENSOR", "False").lower() == "true"


def _effective_device_timeout(value: int) -> int:
    """Never leave HA measurement entities indefinitely available when telemetry stops."""
    return value if value > 0 else 120


DEVICE_TIMEOUT = _effective_device_timeout(int(os.getenv("DEVICE_TIMEOUT", 120)))
MAX_SLOTS = int(os.getenv("MAX_SLOTS", "1"))
MAX_BAT_RAW = os.getenv("MAX_BAT", "auto")
try:
    MAX_BAT: int | str = int(MAX_BAT_RAW)
except ValueError:
    MAX_BAT = MAX_BAT_RAW
KEEP_BATTERY_POSITION = os.getenv("KEEP_BATTERY_POSITION", "False").lower() == "true"
LOG = logging.getLogger(__name__)

_MAX_BAT_CACHE: dict[str, int] = {}

# ------------------- Helpfunctions -------------------

def _normalize_mac_address(value: object) -> str | None:
    """Normalize a valid MAC address to Home Assistant's canonical form."""
    if value is None:
        return None

    text = str(value).strip().lower()
    if not text:
        return None

    compact = text.replace(":", "").replace("-", "").replace(".", "")
    if len(compact) != 12 or any(ch not in "0123456789abcdef" for ch in compact):
        return None

    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def _detect_bat_count(payload: dict) -> int:
    """Return the reported/observed logical battery count without guessing four."""
    bat_cnt = payload.get("bat_cnt")
    if isinstance(bat_cnt, int) and 1 <= bat_cnt <= 4:
        return bat_cnt

    nexa_count = payload.get("batteryPackageQuantity")
    if (
        isinstance(nexa_count, (int, float))
        and not isinstance(nexa_count, bool)
        and float(nexa_count).is_integer()
        and 1 <= int(nexa_count) <= 4
    ):
        return int(nexa_count)

    count = 1
    for bat_num in range(2, 5):
        value = payload.get(f"bat{bat_num}_ser_part_1")
        if value is not None and str(value).strip("\x00 "):
            count = bat_num
    return count


def _resolve_max_bat(device_id: str, payload: dict | None = None) -> int:
    if isinstance(MAX_BAT, int):
        return max(1, min(4, MAX_BAT))
    if payload is not None:
        count = _detect_bat_count(payload)
        _MAX_BAT_CACHE[device_id] = count
        return count
    return _MAX_BAT_CACHE.get(device_id, 1)


def get_known_registers(device_id: str) -> Optional[GroBroRegisters]:
    """Compatibility wrapper around the central device-family registry."""
    return model.get_known_registers(device_id)


def get_device_type_name(device_id: str) -> str:
    """Compatibility wrapper around the central device-family registry."""
    return model.get_device_type_name(device_id)


def _device_label(device_id: str) -> str:
    return f"{get_device_type_name(device_id)} {device_id}"


def _config_register_label(device_id: str, register_no: int) -> str:
    known_registers = get_known_registers(device_id)
    if known_registers:
        for name, reg in known_registers.config_registers.items():
            if reg.growatt.register_no == register_no:
                display_name = getattr(reg.homeassistant, "name", None) or name
                return f'"{display_name}" (register {register_no})'
    return f"register {register_no}"


def map_enum_value(reg, value):
    """Wandelt ENUM-INT_MAP-Werte in Klartext um (falls vorhanden)."""
    try:
        data = getattr(reg.growatt, "data", None)
        if not data or getattr(data, "data_type", None) != "ENUM":
            return value
        enum_opts = getattr(data, "enum_options", None)
        if not enum_opts or getattr(enum_opts, "enum_type", None) != "INT_MAP":
            return value
        return enum_opts.values.get(str(value), enum_opts.values.get(value, str(value)))
    except Exception as e:
        LOG.warning("Enum mapping failed for %s=%s: %s", reg, value, e)
        return value


def make_modbus_command(device_id: str, func: GrowattModbusFunction, register_no: int, value: Optional[int] = None) -> GrowattModbusFunctionSingle:
    """Erzeugt einen GrowattModbusFunctionSingle-Befehl."""
    return GrowattModbusFunctionSingle(
        device_id=device_id,
        function=func,
        register=register_no,
        value=value if value is not None else register_no,
    )


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

def _command_subscriptions() -> list[tuple[str, int]]:
    """Return command topics plus the Home Assistant birth/status topic."""
    subscriptions = [
        (f"{HA_BASE_TOPIC}/{cmd_type}/grobro/+/+/{action}", 0)
        for cmd_type in ("number", "time", "button", "switch", "select", "config")
        for action in ("set", "read")
    ]
    subscriptions.append((f"{HA_BASE_TOPIC}/status", 0))
    return subscriptions


# ------------------- Client-Class -------------------

class Client:
    on_command: Optional[Callable[[GrowattModbusFunctionSingle], None]] = None
    on_config_command: Optional[Callable[[str, int, str], None]] = None
    on_config_read: Optional[Callable[[str, int], None]] = None
    on_config_read_response: Callable[[str, int], None] | None = None

    _client: mqtt.Client
    def __init__(self, mqtt_config: model.MQTTConfig):
        # Runtime state belongs to the client instance. Keeping it here avoids
        # class-level mutable caches and a separate initialization wrapper.
        from grobro.ha.cleanup import initialize_instance_state
        initialize_instance_state(self)

        # Setup target MQTT client for publishing
        LOG.info(
            "Connecting Better GroBro to Home Assistant MQTT at %s:%s",
            mqtt_config.host,
            mqtt_config.port,
        )

        client_id_suffix = os.getenv("MQTT_CLIENT_SUFFIX", "")
        client_id = f"grobro-ha{('-' + client_id_suffix) if client_id_suffix else ''}"

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id
        )
        self._bridge_availability_topic = f"{HA_BASE_TOPIC}/grobro/{client_id}/availability"
        self._client.will_set(self._bridge_availability_topic, "offline", qos=1, retain=True)

        if mqtt_config.username:
            self._client.username_pw_set(mqtt_config.username, mqtt_config.password)
        if mqtt_config.use_tls:
            self._client.tls_set(cert_reqs=ssl.CERT_NONE)
            self._client.tls_insecure_set(True)

        # Register callbacks before connecting so the initial connect and every
        # later reconnect use exactly the same subscription/bootstrap path.
        self._client.on_message = self.__on_message
        self._client.on_connect = self.__on_connect
        self._client.connect(mqtt_config.host, mqtt_config.port, 60)

        # Restore persisted device configs once, keyed by MQTT device id from
        # the filename. This preserves gateway/device identity across restarts.
        from grobro.ha.config_runtime import restore_config_cache_by_filename
        restore_config_cache_by_filename(self)

        self._neo_pv_count: dict[str, int] = {}

    # ------------------- Lifecycle -------------------

    def start(self):
        self._stopped = False
        self._client.loop_start()

        # Stable background services are scheduled directly instead of wrapping
        # Client.start() from multiple runtime modules.
        from grobro.ha.neo_power_runtime import schedule_known_neo_state_probe
        from grobro.ha.time_sync_runtime import schedule_next_time_sync

        schedule_known_neo_state_probe(self)
        schedule_next_time_sync(self)

    def stop(self):
        from grobro.ha.timer_runtime import cancel_runtime_timers

        try:
            with runtime_lock(self):
                self._stopped = True
                with self._config_read_lock, self._device_timer_lock:
                    cancel_runtime_timers(self)
                for device_id in tuple(self._config_cache):
                    self.__publish_availability(device_id, False)
                result = self._client.publish(self._bridge_topic(), "offline", qos=1, retain=True)
                if publish_succeeded(result) and hasattr(result, "wait_for_publish"):
                    try:
                        result.wait_for_publish(timeout=2)
                    except (RuntimeError, ValueError):
                        pass
        finally:
            try:
                self._client.disconnect()
            finally:
                self._client.loop_stop()

    def _bridge_topic(self):
        return getattr(self, "_bridge_availability_topic", f"{HA_BASE_TOPIC}/grobro/grobro-ha/availability")

    # ------------------- Config Handling -------------------

    @guard_runtime
    def set_config(self, device_id: str, config: model.DeviceConfig):
        from grobro.ha.config_runtime import _merge_config, persisted_runtime_data, discovery_config_data, load_persisted_config, persist_device_config
        from grobro.ha.device_inventory import observe_device

        observe_device(device_id)
        if hasattr(self, "_client") and hasattr(self, "_device_last_seen"):
            self.__publish_availability(device_id, True)
            if DEVICE_TIMEOUT > 0:
                self.__reset_device_timer(device_id)

        config_path = f"config_{device_id}.json"
        existing_config = load_persisted_config(self, config_path)
        previous_config = self._config_cache.get(device_id) or existing_config
        effective_config = _merge_config(previous_config, config)

        current_stable_data = persisted_runtime_data(effective_config)
        disk_stable_data = persisted_runtime_data(existing_config)
        discovery_changed = discovery_config_data(previous_config) != discovery_config_data(effective_config)

        needs_sensitive_cleanup = bool(
            existing_config
            and (
                getattr(existing_config, "password", None) is not None
                or getattr(existing_config, "raw", None) is not None
            )
        )

        if (
            existing_config is None
            or needs_sensitive_cleanup
            or disk_stable_data != current_stable_data
        ):
            if persist_device_config(self, device_id, effective_config):
                LOG.info("%s: saved updated device information", _device_label(device_id))
        else:
            LOG.debug("Device metadata unchanged for %s; skipping config save", device_id)

        self._config_cache[device_id] = effective_config

        if not discovery_changed and device_id in self._discovery_cache:
            LOG.debug("No discovery-relevant config change for %s", device_id)
            return

        if device_id in self._discovery_cache:
            self._discovery_cache.remove(device_id)
        getattr(self, "_discovery_signature", {}).pop(device_id, None)
        getattr(self, "_discovery_payload_cache", {}).pop(device_id, None)
        getattr(self, "_migration_done", set()).discard(device_id)
        self.__publish_device_discovery(device_id)

    # ------------------- Publishing -------------------

    def _publish_discovery_message(self, topic, payload=None, *args, **kwargs):
        """Publish discovery with Better GroBro cleanup applied directly."""
        from grobro.ha.discovery_runtime import (
            build_discovery_repair_payload,
            clean_discovery_payload,
            clear_legacy_component_discovery,
            configured_serial,
        )
        from grobro.ha.firmware_runtime import _rewrite_firmware_discovery

        base = HA_BASE_TOPIC
        prefix = f"{base}/device/"
        suffix = "/config"
        is_device_config = topic.startswith(prefix) and topic.endswith(suffix)
        device_id = topic[len(prefix) : -len(suffix)] if is_device_config else None

        if device_id is None:
            state_prefix = f"{base}/grobro/"
            if topic.startswith(state_prefix):
                device_id = topic[len(state_prefix):].split("/", 1)[0]

        if not device_id:
            return self._client.publish(topic, payload, *args, **kwargs)

        repair_done = getattr(self, "_better_312_discovery_repair_done", None)
        if repair_done is None:
            repair_done = set()
            self._better_312_discovery_repair_done = repair_done

        legacy_cleanup_done = getattr(self, "_legacy_discovery_cleanup_done", None)
        if legacy_cleanup_done is None:
            legacy_cleanup_done = set()
            self._legacy_discovery_cleanup_done = legacy_cleanup_done

        if is_device_config and payload:
            try:
                data = json.loads(payload)
                clean_data = clean_discovery_payload(self, device_id, data)

                firmware_version = getattr(
                    self,
                    "_composed_firmware_cache",
                    {},
                ).get(device_id)
                clean_payload = _rewrite_firmware_discovery(
                    device_id,
                    json.dumps(clean_data, separators=(",", ":")),
                    firmware_version,
                )
                clean_data = json.loads(clean_payload)

                if device_id not in repair_done:
                    repair_payload = json.dumps(
                        build_discovery_repair_payload(device_id, clean_data),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    repair_result = self._client.publish(
                        topic,
                        repair_payload,
                        *args,
                        **kwargs,
                    )
                    if publish_succeeded(repair_result):
                        repair_done.add(device_id)

                payload = json.dumps(
                    clean_data,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError):
                pass

        if topic == f"{base}/grobro/{device_id}/serial":
            payload = configured_serial(self, device_id)

        if topic == f"{base}/grobro/{device_id}/sw_version":
            config = getattr(self, "_config_cache", {}).get(device_id)
            sw_version = getattr(config, "sw_version", None) if config else None
            if not sw_version:
                return None
            payload = sw_version

        result = self._client.publish(topic, payload, *args, **kwargs)

        if is_device_config and payload and publish_succeeded(result) and device_id not in legacy_cleanup_done:
            cleanup_succeeded = clear_legacy_component_discovery(
                self._client.publish,
                device_id,
            )
            result = self._client.publish(topic, payload, *args, **kwargs)
            if cleanup_succeeded is False:
                return (mqtt.MQTT_ERR_UNKNOWN, None)
            if publish_succeeded(result):
                legacy_cleanup_done.add(device_id)

        return result

    @guard_runtime
    def publish_input_register(self, state: HomeAssistantInputRegister):
        """Publish one telemetry packet through the optimized HA hot path."""
        from types import SimpleNamespace

        from grobro.ha.battery_position import (
            prepare_battery_payload,
        )
        from grobro.ha.device_inventory import observe_device
        from grobro.ha.firmware_runtime import (
            _firmware_part_names_for_device,
            _invalidate_discovery_for_firmware_change,
            _supports_combined_firmware,
            compose_combined_firmware,
        )
        from grobro.ha.neo_power_runtime import request_initial_neo_inverter_power
        from grobro.ha.performance import (
            _BAT_SERIAL_GROUPS,
            _prepare_payload,
            _register_rules,
            _should_publish_state,
            _should_serialize_state,
        )

        LOG.debug("HA: publish: %s", state)
        device_id = state.device_id
        from grobro.ha.config_runtime import retry_pending_device_config
        retry_pending_device_config(self, device_id)
        state_payload = state.payload
        observe_device(device_id)

        if _supports_combined_firmware(device_id):
            config = self._config_cache.get(device_id)
            datalogger_version = getattr(config, "sw_version", None) if config else None
            firmware_version = compose_combined_firmware(
                state_payload,
                datalogger_version,
                _firmware_part_names_for_device(device_id),
            )
            if firmware_version:
                firmware_cache = getattr(self, "_composed_firmware_cache", None)
                if firmware_cache is None:
                    firmware_cache = {}
                    self._composed_firmware_cache = firmware_cache
                if firmware_cache.get(device_id) != firmware_version:
                    firmware_cache[device_id] = firmware_version
                    _invalidate_discovery_for_firmware_change(self, device_id)

                state_payload = dict(state_payload)
                state_payload["fw_version"] = firmware_version
                state = HomeAssistantInputRegister(
                    device_id=device_id,
                    payload=state_payload,
                )

        stable_logical_max = 1
        if model.uses_noah_protocol(device_id):
            state_payload, stable_logical_max = prepare_battery_payload(
                self, device_id, state_payload, use_stable_auto=KEEP_BATTERY_POSITION,
            )

        effective_max_bat = _resolve_max_bat(device_id, state_payload)
        if stable_logical_max > effective_max_bat:
            effective_max_bat = stable_logical_max

        self.__detect_neo_pv_count(device_id, state_payload)
        self.__publish_device_discovery(device_id, effective_max_bat)
        self.__publish_availability(device_id, True)
        if DEVICE_TIMEOUT > 0:
            self.__reset_device_timer(device_id)

        known_registers = get_known_registers(device_id)
        rules = _register_rules(known_registers)
        prepared_state = (
            state
            if state_payload is state.payload
            else SimpleNamespace(device_id=device_id, payload=state_payload)
        )
        payload = _prepare_payload(
            self,
            prepared_state,
            effective_max_bat,
            known_registers,
            rules,
        )

        if rules[3]:
            expose_combined_battery_serials = model.is_family(device_id, "noah")
            for _bat_num, part_keys, combined_key in _BAT_SERIAL_GROUPS:
                parts = []
                for key in part_keys:
                    value = payload.pop(key, None)
                    if value is not None:
                        parts.append(str(value))
                if expose_combined_battery_serials:
                    combined = "".join(parts).strip()
                    if combined:
                        payload[combined_key] = combined
                    else:
                        payload.pop(combined_key, None)

        if not _should_serialize_state(self, device_id, payload, commit=False):
            LOG.debug(
                "HA state unchanged for %s, skipping serialization and publish",
                device_id,
            )
            return

        payload_json = json.dumps(payload, separators=(",", ":"))
        if not _should_publish_state(self, device_id, payload_json, commit=False):
            LOG.debug("HA state unchanged for %s, skipping publish", device_id)
            return

        topic = f"{HA_BASE_TOPIC}/grobro/{device_id}/state"
        result = self._client.publish(topic, payload_json, retain=False)
        if not publish_succeeded(result):
            return
        _should_serialize_state(self, device_id, payload)
        _should_publish_state(self, device_id, payload_json)
        request_initial_neo_inverter_power(self, device_id)

    @guard_runtime
    def publish_holding_register_input(self, ha_input: HomeAssistantHoldingRegisterInput):
        """Publish changed holding-register states and refresh availability."""
        from grobro.ha.performance import _should_publish_holding_state

        try:
            LOG.debug("HA: publish: %s", ha_input)
            device_id = ha_input.device_id
            self.__publish_availability(device_id, True)
            if DEVICE_TIMEOUT > 0:
                self.__reset_device_timer(device_id)

            for value in ha_input.payload:
                if not _should_publish_holding_state(
                    self,
                    device_id,
                    value.name,
                    value.value,
                    commit=False,
                ):
                    continue
                topic = (
                    f"{HA_BASE_TOPIC}/{value.register_def.type}/grobro/"
                    f"{device_id}/{value.name}/get"
                )
                result = self._client.publish(topic, value.value, retain=True)
                if publish_succeeded(result):
                    _should_publish_holding_state(self, device_id, value.name, value.value)
        except Exception as exc:
            LOG.error("HA: publish msg: %s", exc)

    # ------------------- MQTT Callback -------------------

    @guard_runtime
    def publish_config_register_value(self, device_id: str, register_no: int, value, *, retain=True):
        # R7 is the datalogger password. Clear old retained values without
        # changing the device request/response protocol or exposing the value.
        if register_no == 7:
            value, retain = "", True
        return self._client.publish(
            f"{HA_BASE_TOPIC}/config/grobro/{device_id}/{register_no}/get", value, retain=retain,
        )

    @guard_runtime
    def publish_smart_meter(self, device_id: str, payload: str):
        cache = getattr(self, "_smart_meter_state_cache", None)
        if cache is None:
            cache = self._smart_meter_state_cache = {}
        if cache.get(device_id) == payload:
            return None
        result = self._client.publish(
            f"{HA_BASE_TOPIC}/sensor/grobro/{device_id}/smart_meter/state", payload, retain=False,
        )
        if publish_succeeded(result):
            cache[device_id] = payload
        return result

    def __reset_config_read_state(self) -> None:
        """Cancel an interrupted Read All/config-read cycle.

        MQTT/HA restarts can interrupt a sequence after _read_all_active was set.
        Clearing the transient queue/inflight state on reconnect prevents the
        next Read All press from being treated as a duplicate forever.
        """
        with self._config_read_lock:
            for timer in getattr(self, "_read_all_start_timers", {}).values():
                timer.cancel()
            getattr(self, "_read_all_start_timers", {}).clear()
            for timer in list(self._config_read_timers.values()):
                try:
                    timer.cancel()
                except Exception:  # pragma: no cover
                    pass
            self._config_read_timers.clear()
            self._config_read_queues.clear()
            self._config_read_inflight.clear()
            getattr(self, "_read_all_active", set()).clear()

    @guard_runtime
    def __recover_after_home_assistant_restart(self, client) -> None:
        """Restore command handling after HA Core restarts while MQTT stays up."""
        self.__reset_config_read_state()

        if client is not None:
            client.subscribe(_command_subscriptions())

        # Force the next live telemetry/config packet to rebuild discovery and
        # publish fresh state instead of being suppressed by pre-restart caches.
        from grobro.ha.cleanup import clear_reconnect_caches
        clear_reconnect_caches(self)

        # Retained availability from an earlier HA/process session must not keep
        # stale values looking current. Fresh device traffic sets them online.
        for device_id in self._config_cache:
            self.__publish_availability(device_id, False)

        from grobro.ha.neo_power_runtime import schedule_known_neo_state_probe
        schedule_known_neo_state_probe(self, delay=0.5)

    def __on_connect(self, client, userdata, flags, reason_code, properties):
        LOG.debug("Connected to HA MQTT server with result code %s", reason_code)
        with runtime_lock(self):
            if getattr(self, "_stopped", False) or getattr(reason_code, "is_failure", False):
                return
            self._client.publish(self._bridge_topic(), "online", qos=1, retain=True)
            self.__recover_after_home_assistant_restart(client)
        LOG.info(
            "Connected to Home Assistant; controls and device states are ready"
        )

    def __on_message(self, client, userdata, msg: mqtt.MQTTMessage):
        with runtime_lock(self):
            if getattr(self, "_stopped", False):
                return
            try:
                self.__handle_message(client, userdata, msg)
            except (UnicodeError, ValueError, TypeError, KeyError, OverflowError) as exc:
                LOG.warning("Invalid Home Assistant command on %s (%s)", msg.topic, type(exc).__name__)
            except Exception:
                LOG.exception("Home Assistant command failed on %s", msg.topic)

    def __handle_message(self, client, userdata, msg: mqtt.MQTTMessage):
        # A normal HA Core restart often leaves Mosquitto running, so Paho never
        # reconnects and __on_connect is not called. Home Assistant publishes its
        # MQTT birth message on <discovery-prefix>/status instead. Treat that
        # "online" message as an explicit command/discovery recovery trigger.
        if msg.topic == f"{HA_BASE_TOPIC}/status":
            payload = msg.payload.decode(errors="ignore").strip().lower()
            if payload == "online":
                self.__recover_after_home_assistant_restart(client)
                LOG.info(
                    "Home Assistant restarted; Better GroBro controls were restored"
                )
            return

        parts = msg.topic.removeprefix(f"{HA_BASE_TOPIC}/").split("/")
        if len(parts) != 5 or parts[0] not in {"number", "time", "button", "switch", "select", "config"}:
            return
        cmd_type, _, device_id, cmd_name, action = parts

        LOG.debug("Received %s %s command %s for device %s", cmd_type, action, cmd_name, device_id)

        known_registers = get_known_registers(device_id)
        if not known_registers:
            LOG.info("Ignoring command for unrecognized Growatt device %s", device_id)
            return

        # Buttons
        if cmd_type == "button":
            if cmd_name == "read_all":
                with self._config_read_lock:
                    active = getattr(self, "_read_all_active", None)
                    if active is None:
                        active = set()
                        self._read_all_active = active
                    if device_id in active:
                        LOG.debug(
                            "Read All already active for %s, ignoring duplicate request",
                            device_id,
                        )
                        return
                    active.add(device_id)

                try:
                    # Send all modbus reads first
                    for name, register in known_registers.holding_registers.items():
                        if name.startswith("slot"):
                            try:
                                if int(name[4]) > MAX_SLOTS:
                                    continue
                            except ValueError:
                                continue

                        pos = register.growatt.position
                        self.on_command(
                            make_modbus_command(
                                device_id,
                                GrowattModbusFunction.READ_SINGLE_REGISTER,
                                pos.register_no,
                            )
                        )

                    # Queue config reads
                    if self.on_config_read and known_registers.config_registers:
                        with self._config_read_lock:
                            q = self._config_read_queues.setdefault(device_id, deque())
                            for cfg in known_registers.config_registers.values():
                                q.append(cfg.growatt.register_no)

                        # give the datalogger time to answer modbus reads
                        self.__start_config_read_timer(
                            3.0, self.__kickoff_next_config_read,
                            self._read_all_start_timers, device_id,
                        )
                    else:
                        with self._config_read_lock:
                            self._read_all_active.discard(device_id)
                except Exception:
                    with self._config_read_lock:
                        self.__cancel_config_read_sequence(device_id)
                    raise

                return

            if action == "read":
                reg = known_registers.holding_registers.get(cmd_name)
                if not reg:
                    LOG.error(
                        "Home Assistant requested an unsupported read action \"%s\" for %s",
                        cmd_name,
                        _device_label(device_id),
                    )
                    return

                pos = reg.growatt.position

                self.on_command(
                    make_modbus_command(
                        device_id,
                        GrowattModbusFunction.READ_SINGLE_REGISTER,
                        pos.register_no,
                    )
                )

                return
                
        # Number / Switch / Time / Select
        if cmd_type in {"number", "switch", "time", "select"} and action == "set":
            raw_value = msg.payload.decode().strip()

            reg = known_registers.holding_registers.get(cmd_name)
            if not reg:
                LOG.error(
                    "Home Assistant requested an unsupported setting \"%s\" for %s",
                    cmd_name,
                    _device_label(device_id),
                )
                return

            if cmd_type == "switch":
                if raw_value.upper() not in {"ON", "OFF"}:
                    raise ValueError("invalid switch state")
                parsed_value = 1 if raw_value.upper() == "ON" else 0

            elif cmd_type == "time":
                hour, minute = map(int, raw_value.split(":")[:2])
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("invalid time")
                parsed_value = (hour * 256) + minute

            elif cmd_type == "select":
                options = getattr(
                    reg.homeassistant,
                    "options",
                    None,
                )

                if options:
                    reverse_options = {
                        value: int(key)
                        for key, value in options.items()
                    }

                    if raw_value not in reverse_options:
                        LOG.error(
                            "Home Assistant sent unsupported value \"%s\" for setting \"%s\"",
                            raw_value,
                            cmd_name,
                        )
                        return

                    parsed_value = reverse_options[raw_value]

                else:
                    parsed_value = int(raw_value)

            else:
                parsed_value = int(raw_value)

            pos = reg.growatt.position

            LOG.debug(
                "Setting %s register %s to value %s",
                cmd_name,
                pos.register_no,
                parsed_value,
            )

            write_result = self.on_command(
                make_modbus_command(
                    device_id,
                    GrowattModbusFunction.PRESET_SINGLE_REGISTER,
                    pos.register_no,
                    parsed_value,
                )
            )

            LOG.debug(
                "Triggering read-after-write for Command %s register %s",
                cmd_name,
                pos.register_no,
            )

            self.on_command(
                make_modbus_command(
                    device_id,
                    GrowattModbusFunction.READ_SINGLE_REGISTER,
                    pos.register_no,
                )
            )

            # Some NEO firmware does not reliably answer a standalone read of
            # holding register 0. Mirror the accepted user command as retained
            # switch state; a later real readback still replaces it.
            if (
                cmd_type == "switch"
                and cmd_name == "inverter_power"
                and model.is_family(device_id, "neo")
                and raw_value.upper() in {"ON", "OFF"}
                and publish_succeeded(write_result)
            ):
                from grobro.ha.neo_power_runtime import _publish_retained_switch_state
                _publish_retained_switch_state(self, device_id, raw_value.upper())

            return

        # Config
        if cmd_type == "config" and action == "set":
            register_no = int(cmd_name)
            raw_value = msg.payload.decode().strip()

            # Special case: Sync Time (register 31)
            if register_no == 31:
                from datetime import datetime
                value = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Normal config registers: use numeric or string value as-is
            else:
                value = raw_value

            if self.on_config_command:
                self.on_config_command(device_id, register_no, value)
            return

    # ------------------- Internals -------------------

    @guard_runtime
    def __reset_device_timer(self, device_id: str):
        if getattr(self, "_stopped", False):
            return
        from grobro.ha.timer_runtime import daemon_timer, effective_device_timeout

        now = time.monotonic()
        lock = self._device_timer_lock

        def check_timeout(d_id: str):
            with runtime_lock(self):
                with lock:
                    if getattr(self, "_stopped", False):
                        return
                    last_seen = self._device_last_seen.get(d_id)
                    if last_seen is None:
                        self._device_timers.pop(d_id, None)
                        return

                    timeout = effective_device_timeout(self, d_id)
                    remaining = timeout - (time.monotonic() - last_seen)
                    if remaining > 0:
                        timer = daemon_timer(remaining, check_timeout, args=(d_id,))
                        self._device_timers[d_id] = timer
                        timer.start()
                        return

                    self._device_timers.pop(d_id, None)
                    self._device_last_seen.pop(d_id, None)

                LOG.warning(
                    "%s has stopped sending data; Home Assistant values are now unavailable",
                    _device_label(d_id),
                )
                self.__publish_availability(d_id, False)

        with lock:
            self._device_last_seen[device_id] = now
            timer = self._device_timers.get(device_id)
            if timer is not None and timer.is_alive():
                return

            timer = daemon_timer(
                effective_device_timeout(self, device_id),
                check_timeout,
                args=(device_id,),
            )
            self._device_timers[device_id] = timer
            timer.start()

    def __publish_availability(self, device_id: str, online: bool):
        availability = self._last_availability
        if availability.get(device_id) is online:
            return False

        LOG.debug("Set device %s availability: %s", device_id, online)
        result = self._client.publish(
            f"{HA_BASE_TOPIC}/grobro/{device_id}/availability",
            "online" if online else "offline",
            retain=True,
        )
        if not publish_succeeded(result):
            return False
        if AVAILABILITY_SENSOR:
            result = self._client.publish(
                f"{HA_BASE_TOPIC}/grobro/{device_id}/online",
                "ON" if online else "OFF",
                retain=True,
            )
            if not publish_succeeded(result):
                return False

        availability[device_id] = online
        return True

    def __detect_neo_pv_count(self, device_id: str, payload: dict) -> None:
        if not model.uses_dynamic_pv_count(device_id):
            return
        if self._neo_pv_count.get(device_id) == 4:
            return

        pv = payload.get("Ppv", 0) or 0
        p1 = payload.get("Ppv1", 0) or 0
        p2 = payload.get("Ppv2", 0) or 0
        p3 = payload.get("Ppv3", 0) or 0
        p4 = payload.get("Ppv4", 0) or 0

        if pv > 0:
            if abs(pv - (p1 + p2 + p3 + p4)) < 10 and (p3 > 0 or p4 > 0):
                LOG.info(
                    "%s: detected four PV inputs",
                    _device_label(device_id),
                )
                self._neo_pv_count[device_id] = 4
                return
            if abs(pv - (p1 + p2)) < 10:
                self._neo_pv_count[device_id] = 2
                return

    def __publish_device_discovery(self, device_id: str, effective_max_bat: int | None = None):
        known_registers = get_known_registers(device_id)
        if not known_registers:
            LOG.info(
                "Home Assistant setup skipped for unrecognized Growatt device %s",
                device_id,
            )
            return
        if effective_max_bat is None:
            effective_max_bat = _resolve_max_bat(device_id)

        signature = (
            effective_max_bat,
            self._neo_pv_count.get(device_id),
            runtime_language(),
        )
        # Retry incomplete legacy migration even if the current device-level
        # discovery was already accepted in a previous packet.
        self.__migrate_entity_discovery(device_id, known_registers)
        if (
            device_id in self._discovery_cache
            and self._discovery_signature.get(device_id) == signature
        ):
            return

        topic = f"{HA_BASE_TOPIC}/device/{device_id}/config"

        # prepare discovery payload
        payload: dict = {
            "dev": self.__device_info_from_config(device_id),
            "availability": [
                {"topic": f"{HA_BASE_TOPIC}/grobro/{device_id}/availability"},
                {"topic": self._bridge_topic()},
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
                    if int(entry["name"][4]) > MAX_SLOTS:
                        continue
                except ValueError:
                    continue

            unique_id = f"grobro_{device_id}_cmd_{entry['name']}"
            platform = ha.type

            ha_data = ha.model_dump(exclude_none=True)

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
                    f"{HA_BASE_TOPIC}/{entry['topic_root']}/grobro/"
                    f"{device_id}/{entry['state_id']}/get"
                ),
                **ha_data,
            }
            if platform != "sensor":
                component["command_topic"] = (
                    f"{HA_BASE_TOPIC}/{entry['topic_root']}/grobro/"
                    f"{device_id}/{entry['cmd_id']}/set"
                )
            payload["cmps"][unique_id] = component
        # Config command: Restart Datalogger (Register 32 / Value 1)
        restart_uid = f"grobro_{device_id}_restart_datalogger"
        payload["cmps"][restart_uid] = {
            "platform": "button",
            "name": "Restart Datalogger",
            "command_topic": f"{HA_BASE_TOPIC}/config/grobro/{device_id}/32/set",
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
            "command_topic": f"{HA_BASE_TOPIC}/config/grobro/{device_id}/31/set",
            "unique_id": time_sync_uid
        }

        # Read-All Button
        payload["cmps"][f"grobro_{device_id}_cmd_read_all"] = {
            "command_topic": f"{HA_BASE_TOPIC}/button/grobro/{device_id}/read_all/read",
            "platform": "button",
            "unique_id": f"grobro_{device_id}_cmd_read_all",
            "name": "Read All Values",
        }

        # States
        for state_name, state in known_registers.input_registers.items():
            if not state.homeassistant.publish:
                if not (self._neo_pv_count.get(device_id) == 4 and state_name in ("Vpv3", "Ipv3", "Ppv3", "Vpv4", "Ipv4", "Ppv4", "Epv3_today", "Epv3_total")):
                    continue
            bat_num = _get_bat_number(state_name)
            if bat_num is not None and bat_num > effective_max_bat:
                continue
            if "_ser_part_" in state_name and state_name.startswith("bat"):
                continue
            unique_id = f"grobro_{device_id}_{state_name}"
            payload["cmps"][unique_id] = {
                "platform": "sensor",
                "name": state.homeassistant.name,
                "state_topic": f"{HA_BASE_TOPIC}/grobro/{device_id}/state",
                "value_template": f"{{{{ value_json['{state_name}'] }}}}",
                "unique_id": unique_id,
                "device_class": state.homeassistant.device_class,
                "state_class": state.homeassistant.state_class,
                "unit_of_measurement": state.homeassistant.unit_of_measurement,
                "icon": state.homeassistant.icon,
                **(
                    {
                        "suggested_display_precision":
                        state.homeassistant.suggested_display_precision
                    }
                    if state.homeassistant.suggested_display_precision is not None
                    else {}
                ),
            }

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
                    "state_topic": f"{HA_BASE_TOPIC}/grobro/{device_id}/state",
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
                "state_topic": f"{HA_BASE_TOPIC}/grobro/{device_id}/state",
                "value_template": value_template,
                "unique_id": firmware_unique_id,
                "icon": "mdi:information",
            }

        # Serial Number Entity
        serial_unique_id = f"grobro_{device_id}_serial"
        payload["cmps"][serial_unique_id] = {
            "platform": "sensor",
            "name": "Device SN",
            "state_topic": f"{HA_BASE_TOPIC}/grobro/{device_id}/serial",
            "unique_id": serial_unique_id,
            "icon": "mdi:identifier",
        }
        
        # Device Type Entity
        type_unique_id = f"grobro_{device_id}_type"
        payload["cmps"][type_unique_id] = {
            "platform": "sensor",
            "name": "Device Type",
            "state_topic": f"{HA_BASE_TOPIC}/grobro/{device_id}/type",
            "unique_id": type_unique_id,
            "icon": "mdi:chip",
        }

        # Online Entity
        if DEVICE_TIMEOUT > 0 and AVAILABILITY_SENSOR:
            online_unique_id = f"grobro_{device_id}_online"
            payload["cmps"][online_unique_id] = {
                "platform": "binary_sensor",
                "name": "Online",
                "state_topic": f"{HA_BASE_TOPIC}/grobro/{device_id}/online",
                "device_class": "connectivity",
                "unique_id": online_unique_id,
            }

        payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))

        if self._discovery_payload_cache.get(device_id) == payload_str:
            LOG.debug("Discovery unchanged for %s, skipping", device_id)
            if device_id not in self._discovery_cache:
                self._discovery_cache.append(device_id)
            # trotzdem States aktualisieren
            self._publish_discovery_message(f"{HA_BASE_TOPIC}/grobro/{device_id}/serial", device_id, retain=True)
            self._publish_discovery_message(f"{HA_BASE_TOPIC}/grobro/{device_id}/type", get_device_type_name(device_id), retain=True)
            self._publish_discovery_message(f"{HA_BASE_TOPIC}/grobro/{device_id}/sw_version", device_id, retain=True)
            self._discovery_signature[device_id] = signature
            return

        LOG.info(
            "Home Assistant: updating entities for %s",
            _device_label(device_id),
        )
        self._publish_discovery_message(topic, "", retain=True)  # force HA to refresh
        result = self._publish_discovery_message(topic, payload_str, retain=True)
        if not publish_succeeded(result):
            return
        self._discovery_payload_cache[device_id] = payload_str
        if device_id not in self._discovery_cache:
            self._discovery_cache.append(device_id)

        self._publish_discovery_message(f"{HA_BASE_TOPIC}/grobro/{device_id}/serial", device_id, retain=True)
        self._publish_discovery_message(f"{HA_BASE_TOPIC}/grobro/{device_id}/type", get_device_type_name(device_id), retain=True)
        self._discovery_signature[device_id] = signature

    def __migrate_entity_discovery(self, device_id: str, known_registers: GroBroRegisters):
        if device_id in self._migration_done:
            return

        results = []
        old_entities = [("set_wirk", "number")]
        for e_name, e_type in old_entities:
            results.append(self._publish_discovery_message(
                f"{HA_BASE_TOPIC}/{e_type}/grobro/{device_id}_{e_name}/config",
                json.dumps({"migrate_discovery": True}),
                retain=True,
            ))
        for cmd_name, cmd in known_registers.holding_registers.items():
            cmd_type = cmd.homeassistant.type
            results.append(self._publish_discovery_message(
                f"{HA_BASE_TOPIC}/{cmd_type}/grobro/{device_id}_{cmd_name}/config",
                json.dumps({"migrate_discovery": True}),
                retain=True,
            ))
            results.append(self._publish_discovery_message(
                f"{HA_BASE_TOPIC}/{cmd_type}/grobro/{device_id}_{cmd_name}_read/config",
                json.dumps({"migrate_discovery": True}),
                retain=True,
            ))
        for state_name in known_registers.input_registers:
            results.append(self._publish_discovery_message(
                f"{HA_BASE_TOPIC}/sensor/grobro/{device_id}_{state_name}/config",
                json.dumps({"migrate_discovery": True}),
                retain=True,
            ))

        if all(publish_succeeded(result) for result in results):
            self._migration_done.add(device_id)

    def __device_info_from_config(self, device_id: str):
        # Find matching config
        config = self._config_cache.get(device_id)
        config_path = f"config_{device_id}.json"

        # Fallback: try loading from file
        if not config:
            config = model.DeviceConfig.from_file(config_path)
            self._config_cache[device_id] = config
            LOG.info(
                "%s: restored saved device information",
                _device_label(device_id),
            )

        # Fallback 2: save minimal config if it was neither in cache nor on disk
        if not config:
            config = model.DeviceConfig(serial_number=device_id)
            from grobro.ha.config_runtime import persist_device_config
            persist_device_config(self, device_id, config)
            self._config_cache[device_id] = config
            LOG.info(
                "%s: created initial device information",
                _device_label(device_id),
            )

        # Device Info for HA
        device_info: dict = {
            "identifiers": [device_id],
            "name": f"Growatt {device_id}",
            "manufacturer": "Growatt",
            "serial_number": device_id,
        }

        type_name = get_device_type_name(device_id)

        known_model_id = {
            "55": "NEO-series",
            "72": "NEXA-series",
            "61": "NOAH-series",
        }.get(getattr(config, "device_type", None))

        if known_model_id:
            device_info["model"] = known_model_id
        else:
            device_info["model"] = f"{type_name}-series"

        if getattr(config, "model_id", None):
            device_info["model"] += f" ({config.model_id})"
        if getattr(config, "sw_version", None):
            device_info["sw_version"] = config.sw_version
        if getattr(config, "hw_version", None):
            device_info["hw_version"] = config.hw_version
        if getattr(config, "mac_address", None):
            mac = _normalize_mac_address(config.mac_address)
            if mac:
                device_info["connections"] = [["mac", mac]]

        return device_info

    def __start_config_read_timer(self, delay, callback, timers, device_id, *args):
        """Run only if this timer still belongs to the current read sequence."""
        def run():
            with runtime_lock(self):
                if timers.get(device_id) is timer:
                    callback(device_id, *args)

        timer = Timer(delay, run)
        timer.daemon = True
        timers[device_id] = timer
        timer.start()

    def __cancel_config_read_sequence(self, device_id: str):
        """Release failed reads; caller must hold _config_read_lock."""
        self._config_read_inflight.pop(device_id, None)
        self._config_read_queues.pop(device_id, None)
        for timers in (self._config_read_timers, getattr(self, "_read_all_start_timers", {})):
            timer = timers.pop(device_id, None)
            if timer is not None:
                timer.cancel()
        getattr(self, "_read_all_active", set()).discard(device_id)

    @guard_runtime
    def __kickoff_next_config_read(self, device_id: str):
        with self._config_read_lock:
            timer = getattr(self, "_read_all_start_timers", {}).pop(device_id, None)
            if timer is not None:
                timer.cancel()
            # already waiting for a response
            if device_id in self._config_read_inflight:
                return

            q = self._config_read_queues.get(device_id)
            if not q:
                getattr(self, "_read_all_active", set()).discard(device_id)
                return

            register_no = q.popleft()
            self._config_read_inflight[device_id] = register_no

            # Arm before sending: a fast/synchronous response may already start
            # the next read and must not have its timer overwritten afterward.
            try:
                self.__start_config_read_timer(
                    60, self.__config_read_timeout,
                    self._config_read_timers, device_id, register_no,
                )
            except Exception:
                self.__cancel_config_read_sequence(device_id)
                raise

        if self.on_config_read:
            try:
                self.on_config_read(device_id, register_no)
            except Exception:
                with self._config_read_lock:
                    self.__cancel_config_read_sequence(device_id)
                raise

    @guard_runtime
    def __config_read_timeout(self, device_id: str, register_no: int):
        with self._config_read_lock:
            inflight = self._config_read_inflight.get(device_id)
            if inflight != register_no:
                return

            LOG.info(
                "%s did not answer the Better GroBro request for %s; continuing with the next setting",
                _device_label(device_id),
                _config_register_label(device_id, register_no),
            )

            self._config_read_inflight.pop(device_id, None)
            self._config_read_timers.pop(device_id, None)

        # continue with next queued register
        self.__kickoff_next_config_read(device_id)

    @guard_runtime
    def handle_config_read_response(self, device_id: str, register_no: int):
        # A successful config read is a direct response from the device and must
        # refresh its availability even if regular telemetry is infrequent.
        self.__publish_availability(device_id, True)
        if DEVICE_TIMEOUT > 0:
            self.__reset_device_timer(device_id)
        with self._config_read_lock:
            inflight = self._config_read_inflight.get(device_id)
            if inflight != register_no:
                return

            LOG.debug(
                "Config read completed for %s register=%s",
                device_id,
                register_no,
            )

            timer = self._config_read_timers.pop(device_id, None)
            if timer:
                timer.cancel()

            self._config_read_inflight.pop(device_id, None)

        # continue with next queued read
        self.__kickoff_next_config_read(device_id)
