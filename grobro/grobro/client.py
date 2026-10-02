"""
Client for the grobro mqtt side, handling messages from/to
* growatt cloud
* growatt devices
"""

import logging
import os
import re
import ssl
import struct
import threading
from collections import deque
from functools import lru_cache
from typing import Callable

import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessage

from grobro import model
from grobro.grobro import parser
from grobro.grobro.builder import (
    append_crc,
    build_config_read_packet,
    build_config_write_packet,
    scramble,
)
from grobro.grobro.cloud_policy import CloudForwardingPolicy
from grobro.grobro.noah_heater import heater_state_from_unscrambled
from grobro.grobro.raw_dump import dump_message_jsonl
from grobro.grobro.register_debug import (
    REGISTER_DEBUG as REGISTER_CAPTURE_ENABLED,
    capture_modbus_message,
    capture_noah_0103,
)
from grobro.grobro.noah_traffic_debug import (
    REGISTER_DEBUG as NOAH_TRAFFIC_CAPTURE_ENABLED,
    capture_noah_mqtt_traffic,
)
from grobro.model.growatt_registers import (
    HomeAssistantHoldingRegisterInput,
    HomeAssistantHoldingRegisterValue,
    HomeAssistantInputRegister,
)
from grobro.model.modbus_function import GrowattModbusFunctionSingle
from grobro.model.modbus_message import GrowattModbusFunction, GrowattModbusMessage
from grobro.model.mqtt_config import MQTTConfig


_DEVICE_ID_RE = re.compile(r"[^A-Za-z0-9]")


@lru_cache(maxsize=256)
def _extract_device_id(topic: str) -> str:
    """Extract and cache the device serial from the last MQTT topic segment.

    Growatt device serials are alphanumeric (A-Z, 0-9). Some dongles
    (e.g. ShineWiFi-X2 / XH family) include stray trailing bytes in the
    SUBSCRIBE topic, such as `s/33/ZGQ0F5601J?\\x18`. Strip everything
    that isn't a valid serial character.
    """
    return _DEVICE_ID_RE.sub("", str(topic).rsplit("/", 1)[-1])


def _known_registers_for_device(device_id: str):
    """Compatibility wrapper around the central device-family registry."""
    return model.get_known_registers(device_id)


def _device_label(device_id: str) -> str:
    """Human-readable device label for user-facing logs."""
    return f"{model.get_device_type_name(device_id)} {device_id}"


def _config_register_name(device_id: str, register_no: int) -> str | None:
    """Return the configured human-readable name for a config register."""
    known_registers = _known_registers_for_device(device_id)
    if known_registers:
        for name, reg in known_registers.config_registers.items():
            if reg.growatt.register_no == register_no:
                return getattr(reg.homeassistant, "name", None) or name
    return None


def _config_register_label(device_id: str, register_no: int) -> str:
    """Return a stable user-facing config register label."""
    display_name = _config_register_name(device_id, register_no)
    if display_name:
        return f'"{display_name}" (register {register_no})'
    return f'"Unknown setting" (register {register_no})'


def _publish_checked(client, topic: str, payload=None, **kwargs):
    """Publish and warn when Paho rejects the request locally."""
    if (
        NOAH_TRAFFIC_CAPTURE_ENABLED
        and payload is not None
        and "/33/" in str(topic)
    ):
        device_id = _extract_device_id(topic)
        if device_id.startswith("0PVP"):
            properties = kwargs.get("properties")
            if properties is MQTT_PROP_FORWARD_GROWATT:
                direction = "grobro_to_device_from_cloud"
            elif properties is MQTT_PROP_FORWARD_HA:
                direction = "grobro_to_device_from_ha"
            else:
                direction = "grobro_to_cloud_or_device"
            try:
                decoded = parser.unscramble(payload)
            except Exception:
                decoded = None
            capture_noah_mqtt_traffic(
                device_id=device_id,
                direction=direction,
                topic=topic,
                payload=payload,
                decoded=decoded,
                qos=kwargs.get("qos"),
                retain=kwargs.get("retain"),
                forwarded_for=None,
            )

    result = client.publish(topic, payload, **kwargs)
    status = getattr(result, "rc", None)
    if status is None:
        try:
            status = result[0]
        except (TypeError, IndexError, KeyError):
            status = None
    if status not in (None, 0):
        LOG.warning("Could not send an MQTT message to %s (error code %s)", topic, status)
    return result


LOG = logging.getLogger(__name__)
HA_BASE_TOPIC = os.getenv("HA_BASE_TOPIC", "homeassistant")

# Preserve the established module-level settings for compatibility while
# delegating all forwarding decisions to one focused policy object.
GROWATT_CLOUD = os.getenv("GROWATT_CLOUD", "false").strip()
GROWATT_CLOUD_CONFIG_FILTER = os.getenv("GROWATT_CLOUD_CONFIG_FILTER", "false").lower()
_CLOUD_POLICY = CloudForwardingPolicy.parse(
    GROWATT_CLOUD,
    GROWATT_CLOUD_CONFIG_FILTER,
)
GROWATT_CLOUD_ENABLED = _CLOUD_POLICY.enabled
GROWATT_CLOUD_FILTER = set(_CLOUD_POLICY.allowlist)
# Kept as a compatibility alias for older tests/extensions that patched this
# internal value. Runtime decisions still go through CloudForwardingPolicy.
_cloud_lower = GROWATT_CLOUD.lower()


def _current_cloud_policy() -> CloudForwardingPolicy:
    """Resolve cloud policy from compatibility module variables.

    The public/legacy module variables remain patchable for tests and external
    integrations, while all actual allow/block decisions are centralized in
    CloudForwardingPolicy.
    """
    if not GROWATT_CLOUD_ENABLED:
        cloud_value = "false"
    elif _cloud_lower == "true":
        cloud_value = "true"
    elif GROWATT_CLOUD_FILTER:
        cloud_value = ",".join(sorted(GROWATT_CLOUD_FILTER))
    else:
        cloud_value = GROWATT_CLOUD or "true"
    return CloudForwardingPolicy.parse(cloud_value, GROWATT_CLOUD_CONFIG_FILTER)


DUMP_MESSAGES = os.getenv("DUMP_MESSAGES", "false").lower() == "true"
DUMP_DIR = os.getenv("DUMP_DIR", "/dump")

# Property to flag messages forwarded from growatt cloud
MQTT_PROP_FORWARD_GROWATT = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
MQTT_PROP_FORWARD_GROWATT.UserProperty = [("forwarded-for", "growatt")]

# Property to flag messages as forwarded from ha
MQTT_PROP_FORWARD_HA = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
MQTT_PROP_FORWARD_HA.UserProperty = [("forwarded-for", "ha")]


class Client:
    on_config: Callable[[str, model.DeviceConfig], None]
    on_input_register: Callable[HomeAssistantInputRegister, None]
    on_holding_register_input: Callable[HomeAssistantHoldingRegisterInput, None]

    _client: mqtt.Client
    _forward_mqtt_config: model.MQTTConfig

    def __init__(self, grobro_mqtt: MQTTConfig, forward_mqtt: MQTTConfig):
        LOG.info(
            "Starting Better GroBro MQTT connection to %s:%s",
            grobro_mqtt.host,
            grobro_mqtt.port,
        )
        client_id_suffix = os.getenv("MQTT_CLIENT_SUFFIX", "")
        client_id = f"grobro-grobro{('-' + client_id_suffix) if client_id_suffix else ''}"

        self._client = mqtt.Client(
            client_id=client_id,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            protocol=mqtt.MQTTv5,
        )

        if grobro_mqtt.username and grobro_mqtt.password:
            self._client.username_pw_set(grobro_mqtt.username, grobro_mqtt.password)
        if grobro_mqtt.use_tls:
            self._client.tls_set(cert_reqs=ssl.CERT_NONE)
            self._client.tls_insecure_set(True)
        self._client.connect(grobro_mqtt.host, grobro_mqtt.port, 60)
        self._client.on_message = self.__on_message
        self._client.on_connect = self.__on_connect
        self._forward_mqtt_config = forward_mqtt
        self._forward_clients: dict[str, mqtt.Client] = {}
        self._forward_ready: dict[str, threading.Event] = {}
        self._forward_pending: dict[str, deque[tuple[str, bytes, int, bool]]] = {}
        self._forward_pending_lock = threading.Lock()
        self._forward_overflow_warned: set[str] = set()
        self._ptq_for_raq: dict[str, str] = {}
        self._smart_meter_state_cache: dict[str, str] = {}
        self._pending_config_writes: dict[str, deque[int]] = {}
        self._neo_version_probe_requested: set[str] = set()

    def start(self):
        LOG.debug("GroBro: Start")
        self._client.loop_start()

    def stop(self):
        LOG.debug("GroBro: Stop")
        self._client.loop_stop()
        self._client.disconnect()
        for forward_client in list(self._forward_clients.values()):
            try:
                forward_client.loop_stop()
            finally:
                forward_client.disconnect()
        self._forward_clients.clear()
        self._forward_ready.clear()
        with self._forward_pending_lock:
            self._forward_pending.clear()
            self._forward_overflow_warned.clear()
        self._pending_config_writes.clear()

    def __probe_neo_versions(self, device_id: str) -> None:
        """Issue one conservative NEO config-version probe in register-debug mode."""
        if (
            not REGISTER_CAPTURE_ENABLED
            or not model.is_family(device_id, "neo")
            or device_id in self._neo_version_probe_requested
        ):
            return

        self._neo_version_probe_requested.add(device_id)
        LOG.info(
            "%s: diagnostic version probe reading config 21, then 22 after its response",
            _device_label(device_id),
        )

        # Config parameter 21 is the common Growatt TLV software-version field.
        # Request 22 only after 21 has answered so the NEO never receives
        # concurrent diagnostic config reads.
        self.send_config_read_message(device_id, 21)

    def send_command(self, cmd: GrowattModbusFunctionSingle):
        scrambled = scramble(cmd.build_grobro())
        final_payload = append_crc(scrambled)

        topic = f"s/33/{cmd.device_id}"
        LOG.debug("Send command: %s: %s: %s", type(cmd).__name__, topic, cmd)

        return _publish_checked(
            self._client,
            topic,
            final_payload,
            properties=MQTT_PROP_FORWARD_HA,
        )

    def send_config_read_message(self, device_id: str, register_no: int):
        final_payload = build_config_read_packet(device_id, register_no)
        topic = f"s/33/{device_id}"

        LOG.info(
            "Better GroBro -> %s: request config %s",
            _device_label(device_id),
            _config_register_label(device_id, register_no),
        )
        return _publish_checked(
            self._client,
            topic,
            final_payload,
            properties=MQTT_PROP_FORWARD_HA,
        )

    def send_config_message(self, device_id: str, register_no: int, value: str):
        final_payload = build_config_write_packet(device_id, register_no, value)
        topic = f"s/33/{device_id}"

        # Never log the value: config registers can contain credentials.
        LOG.info(
            "Better GroBro -> %s: write config %s",
            _device_label(device_id),
            _config_register_label(device_id, register_no),
        )
        result = _publish_checked(
            self._client,
            topic,
            final_payload,
            properties=MQTT_PROP_FORWARD_HA,
        )
        status = getattr(result, "rc", None)
        if status is None:
            try:
                status = result[0]
            except (TypeError, IndexError, KeyError):
                status = None
        if status in (None, 0):
            self._pending_config_writes.setdefault(device_id, deque()).append(
                int(register_no)
            )
        return result

    def __on_connect(self, client, userdata, flags, reason_code, properties):
        LOG.debug("Connected to GroBro MQTT server with result code %s", reason_code)
        self._smart_meter_state_cache.clear()
        client.subscribe("c/#")

    def __on_message(self, client, userdata, msg: MQTTMessage):
        # check for forwarded messages and ignore them
        forwarded_for = get_property(msg, "forwarded-for")
        if forwarded_for in {"ha", "growatt"}:
            if NOAH_TRAFFIC_CAPTURE_ENABLED:
                debug_device_id = _extract_device_id(msg.topic)
                if debug_device_id.startswith("0PVP"):
                    try:
                        decoded = parser.unscramble(msg.payload)
                    except Exception:
                        decoded = None
                    capture_noah_mqtt_traffic(
                        device_id=debug_device_id,
                        direction="device_to_grobro",
                        topic=msg.topic,
                        payload=msg.payload,
                        decoded=decoded,
                        qos=getattr(msg, "qos", None),
                        retain=getattr(msg, "retain", None),
                        forwarded_for=forwarded_for,
                    )
            LOG.debug("Message forwarded from %s. Skipping...", forwarded_for)
            return

        if LOG.isEnabledFor(logging.DEBUG):
            file_name = get_property(msg, "file")
            LOG.debug("Received message (%s): %s: %s", file_name, msg.topic, msg.payload)
        if DUMP_MESSAGES:
            dump_message_binary(msg.topic, msg.payload)
        try:
            device_id = _extract_device_id(msg.topic)
            if not device_id:
                LOG.debug("Ignoring MQTT message without a usable device id: %s", msg.topic)
                return

            cloud_policy = _current_cloud_policy()
            if cloud_policy.allows_device(device_id):
                try:
                    self.__publish_to_growatt_server(
                        device_id,
                        msg.topic,
                        msg.payload,
                        msg.qos,
                        msg.retain,
                    )
                except Exception as exc:
                    LOG.error("Could not forward device data to Growatt Cloud (%s)", exc)

            unscrambled = parser.unscramble(msg.payload)
            if NOAH_TRAFFIC_CAPTURE_ENABLED and device_id.startswith("0PVP"):
                capture_noah_mqtt_traffic(
                    device_id=device_id,
                    direction="device_to_grobro",
                    topic=msg.topic,
                    payload=msg.payload,
                    decoded=unscrambled,
                    qos=getattr(msg, "qos", None),
                    retain=getattr(msg, "retain", None),
                    forwarded_for=forwarded_for,
                )
            if len(unscrambled) < 8:
                LOG.debug("Ignoring truncated Growatt message for %s", device_id)
                return
            if LOG.isEnabledFor(logging.DEBUG):
                LOG.debug("Received: %s %s", msg.topic, unscrambled.hex(" "))

            # Read msg_type from both possible offsets
            msg_type_4 = struct.unpack_from(">H", unscrambled, 4)[0]
            msg_type = struct.unpack_from(">H", unscrambled, 6)[0]
            heater_state = heater_state_from_unscrambled(unscrambled, device_id)

            # Config TLV: NEO=340,341 / NOAH=387 at offset 4; ShineWeLink=0x0129 at offset 6
            if msg_type_4 in (340, 341, 387) or msg_type == 0x0129:
                config_offset = parser.find_config_offset(unscrambled)
                config = parser.parse_config_type(unscrambled, config_offset)
                if config and (
                    msg_type_4 in (340, 341, 387)
                    or msg_type == 0x0129
                    or config.serial_number
                ):
                    self.on_config(device_id, config)
                    LOG.info(
                        "%s -> Better GroBro: device settings received",
                        _device_label(device_id),
                    )
                    # Extract PTQ inverter serial from ShineWeLink dongle config
                    if msg_type == 0x0129 and len(unscrambled) >= 68:
                        ptq_serial = (
                            unscrambled[38:68]
                            .rstrip(b"\x00")
                            .decode("ascii", errors="replace")
                            .strip()
                        )
                        if ptq_serial.startswith("PTQ"):
                            self._ptq_for_raq[device_id] = ptq_serial
                            ptq_config = model.DeviceConfig(serial_number=ptq_serial)
                            ptq_config.device_type = "55"
                            if getattr(config, "model_id", None):
                                ptq_config.model_id = config.model_id
                            if getattr(config, "sw_version", None):
                                ptq_config.sw_version = config.sw_version
                            self.on_config(ptq_serial, ptq_config)
                            LOG.info(
                                "Detected NEO inverter %s behind ShineWeLink %s",
                                ptq_serial,
                                device_id,
                            )
                return

            # Config READ response (281). NEO can bundle multiple config
            # register TLVs in one response (observed: R76 Wi-Fi RSSI + R5).
            if msg_type == 281:
                cfg = parser.parse_config_message(unscrambled)
                entries = cfg.get("entries") or [
                    {
                        "register_no": cfg["register_no"],
                        "value": cfg["value"],
                    }
                ]
                is_compound = len(entries) > 1

                if is_compound:
                    LOG.debug(
                        "Received compound config response for %s: %s",
                        cfg["device_id"],
                        ", ".join(
                            f"reg={entry['register_no']} value={entry['value']!r}"
                            for entry in entries
                        ),
                    )
                else:
                    LOG.info(
                        "%s -> Better GroBro: received %s",
                        _device_label(cfg["device_id"]),
                        _config_register_label(
                            cfg["device_id"],
                            cfg["register_no"],
                        ),
                    )

                known_registers = _known_registers_for_device(cfg["device_id"])
                for entry in entries:
                    register_no = entry["register_no"]
                    value = entry["value"]

                    if known_registers:
                        for reg in known_registers.config_registers.values():
                            if reg.growatt.register_no == register_no:
                                if reg.growatt.data.data_type == "INT":
                                    try:
                                        value = int(value)
                                    except (TypeError, ValueError):
                                        LOG.debug(
                                            "Invalid integer config value for %s reg=%s",
                                            cfg["device_id"],
                                            register_no,
                                        )
                                        break
                                break

                    if (
                        REGISTER_CAPTURE_ENABLED
                        and model.is_family(cfg["device_id"], "neo")
                        and register_no in (21, 22)
                    ):
                        LOG.info(
                            "%s: diagnostic config register %s=%r",
                            _device_label(cfg["device_id"]),
                            register_no,
                            value,
                        )
                        if register_no == 21:
                            self.send_config_read_message(cfg["device_id"], 22)

                    topic = (
                        f"{HA_BASE_TOPIC}/config/grobro/"
                        f"{cfg['device_id']}/{register_no}/get"
                    )
                    _publish_checked(self._client, topic, value, retain=True)

                    if self.on_config_read_response:
                        self.on_config_read_response(
                            cfg["device_id"],
                            register_no,
                        )
                return

            # Config WRITE response (280)
            if msg_type == 280:
                cfg = parser.parse_config_ack(unscrambled)
                ack_device_id = cfg["device_id"]
                parsed_register = cfg["register_no"]
                pending = self._pending_config_writes.get(ack_device_id)
                if _config_register_name(ack_device_id, parsed_register):
                    register_no = parsed_register
                    if pending and parsed_register in pending:
                        pending.remove(parsed_register)
                elif pending:
                    register_no = pending.popleft()
                    LOG.debug(
                        "%s config acknowledgement reported unknown register %s; "
                        "matched it to the pending Better GroBro write for register %s",
                        _device_label(ack_device_id),
                        parsed_register,
                        register_no,
                    )
                else:
                    register_no = parsed_register

                if pending is not None and not pending:
                    self._pending_config_writes.pop(ack_device_id, None)

                LOG.info(
                    "%s -> Better GroBro: setting accepted for %s",
                    _device_label(ack_device_id),
                    _config_register_label(
                        ack_device_id,
                        register_no,
                    ),
                )
                return

            # NOAH/NEXA Smart Meter (EcoTracker, Shelly etc.) JSON data (0x6F64)
            if msg_type == 0x6F64:
                smart_meter = parser.parse_noah_6f64(unscrambled)
                smart_meter_device_id = smart_meter["device_id"]
                smart_meter_data = smart_meter["data"]
                LOG.debug(
                    "Smart Meter data for %s: %s",
                    smart_meter_device_id,
                    smart_meter_data,
                )

                if self._smart_meter_state_cache.get(smart_meter_device_id) == smart_meter_data:
                    LOG.debug(
                        "Smart Meter state unchanged for %s, skipping publish",
                        smart_meter_device_id,
                    )
                    return

                topic = (
                    f"{HA_BASE_TOPIC}/sensor/grobro/"
                    f"{smart_meter_device_id}/smart_meter/state"
                )
                _publish_checked(
                    self._client,
                    topic,
                    smart_meter_data,
                    retain=False,
                )
                self._smart_meter_state_cache[smart_meter_device_id] = smart_meter_data
                return

            # NOAH/NEXA-specific message types (FE19 config, 0103 holding regs, etc.)
            noah_msg = parser.parse_noah_message(unscrambled)
            if noah_msg and noah_msg.get("message_type") == 0xFE19:
                if model.uses_noah_protocol(device_id):
                    config = noah_msg.get("config")
                    if config and config.serial_number:
                        LOG.info(
                            "%s -> Better GroBro: device information received (software %s)",
                            _device_label(config.serial_number),
                            config.sw_version or "unknown",
                        )
                        self.on_config(device_id, config)
                        return

            # 0x0103 uses a NOAH/NEO-specific payload with an embedded device
            # identifier and optional embedded register block. It is not a
            # generic Modbus block starting directly after the common header.
            # Keep 0x0103 out of the generic Modbus path; optional diagnostics
            # consume the already-decoded result directly.
            if noah_msg and noah_msg.get("message_type") == 0x0103:
                if REGISTER_CAPTURE_ENABLED:
                    capture_noah_0103(unscrambled, noah_msg)
                LOG.debug("Handled NOAH/NEO 0x0103 message for %s", device_id)
                return

            # Generic modbus message
            modbus_message = GrowattModbusMessage.parse_grobro(unscrambled)
            if REGISTER_CAPTURE_ENABLED:
                capture_modbus_message(modbus_message)
            LOG.debug("Received modbus message: %s", modbus_message)

            if modbus_message:
                ptq_device_id = self._ptq_for_raq.get(device_id)
                modbus_device_id = ptq_device_id or device_id
                known_registers = _known_registers_for_device(modbus_device_id)
                if not known_registers:
                    LOG.info(
                        "Ignoring data from unrecognized Growatt device %s",
                        device_id,
                    )
                    return

                if modbus_message.function == GrowattModbusFunction.READ_SINGLE_REGISTER:
                    state = HomeAssistantHoldingRegisterInput(device_id=modbus_device_id)
                    for name, register in known_registers.holding_registers.items():
                        if register.growatt is None:
                            continue
                        data_raw = modbus_message.get_data(register.growatt.position)
                        value = register.growatt.data.parse(data_raw)
                        if value is None:
                            continue
                        if register.homeassistant.type == "switch":
                            value = "ON" if value == 1 else "OFF"
                        state.payload.append(
                            HomeAssistantHoldingRegisterValue(
                                name=name,
                                value=value,
                                register=register.homeassistant,
                            )
                        )
                    if state.payload:
                        self.on_holding_register_input(state)
                    return

                if modbus_message.function == GrowattModbusFunction.READ_INPUT_REGISTER:
                    if (
                        REGISTER_CAPTURE_ENABLED
                        and model.is_family(modbus_device_id, "neo")
                        and any(
                            block is not None
                            and block.start <= 3000 <= block.end
                            for block in modbus_message.register_blocks
                        )
                    ):
                        self.__probe_neo_versions(modbus_device_id)

                    state = HomeAssistantInputRegister(device_id=modbus_device_id)
                    for name, register in known_registers.input_registers.items():
                        data_raw = modbus_message.get_data(register.growatt.position)
                        value = register.growatt.data.parse(data_raw)
                        if value is None:
                            continue
                        # Workaround for broken NEO night messages with impossible PV power.
                        if (
                            name == "Ppv"
                            and isinstance(value, (int, float))
                            and value > 1_000_000
                        ):
                            LOG.debug("Dropping bad payload: %s", device_id)
                            return
                        state.payload[name] = value
                    if heater_state is not None:
                        state.payload["heater"] = heater_state
                    if state.payload:
                        self.on_input_register(state)
                    return

                return

            if LOG.isEnabledFor(logging.DEBUG):
                LOG.debug("Unknown msg_type %s: %s", msg_type, unscrambled.hex())
        except (struct.error, TypeError, ValueError, KeyError) as exc:
            LOG.error("Received an unreadable device message on %s (%s)", msg.topic, exc)
        except Exception as exc:
            LOG.exception("Unexpected error while processing device data from %s (%s)", msg.topic, exc)

    def __on_message_forward_client(self, client, userdata, msg: MQTTMessage):
        LOG.debug("Received Growatt forward message: %s: %s", msg.topic, msg.payload)
        if DUMP_MESSAGES:
            dump_message_binary(msg.topic, msg.payload)
        try:
            device_id = _extract_device_id(msg.topic)
            if not device_id:
                return

            unscrambled = parser.unscramble(msg.payload)
            if NOAH_TRAFFIC_CAPTURE_ENABLED and device_id.startswith("0PVP"):
                capture_noah_mqtt_traffic(
                    device_id=device_id,
                    direction="cloud_to_grobro",
                    topic=msg.topic,
                    payload=msg.payload,
                    decoded=unscrambled,
                    qos=getattr(msg, "qos", None),
                    retain=getattr(msg, "retain", None),
                    forwarded_for=get_property(msg, "forwarded-for"),
                )
            if len(unscrambled) < 8:
                LOG.debug("Ignoring truncated Growatt cloud message for %s", device_id)
                return
            if LOG.isEnabledFor(logging.DEBUG):
                LOG.debug("Received Growatt forward: %s %s", msg.topic, unscrambled.hex(" "))

            cloud_policy = _current_cloud_policy()
            if not cloud_policy.allows_device(device_id):
                LOG.debug(
                    "Dropping Growatt message for device %s not allowed by cloud policy",
                    device_id,
                )
                return

            # Cloud configuration filtering belongs in the Cloud -> device path.
            cloud_msg_type = struct.unpack_from(">H", unscrambled, 6)[0]

            # Config register reads (0x0119) can be issued periodically by
            # Growatt Cloud. Log the requested register at INFO so these reads
            # can be distinguished from Better GroBro's own explicit reads.
            if cloud_msg_type == 0x0119 and len(unscrambled) >= 42:
                cloud_register = struct.unpack_from(">H", unscrambled, 40)[0]
                LOG.info(
                    "Growatt Cloud -> %s: request config %s",
                    _device_label(device_id),
                    _config_register_label(device_id, cloud_register),
                )
            if cloud_policy.should_block_cloud_message(cloud_msg_type):
                LOG.warning(
                    "Growatt Cloud -> %s: settings change blocked by Better GroBro",
                    _device_label(device_id),
                )
                return

            LOG.debug("Forwarding message from Growatt for client %s", device_id)
            topic = msg.topic.split("/")[0] + "/33/" + device_id
            _publish_checked(
                self._client,
                topic,
                payload=msg.payload,
                qos=msg.qos,
                retain=msg.retain,
                properties=MQTT_PROP_FORWARD_GROWATT,
            )
        except (struct.error, TypeError, ValueError) as exc:
            LOG.error("Received an unreadable message from Growatt Cloud (%s)", exc)
        except Exception as exc:
            LOG.exception("Unexpected error while handling Growatt Cloud data (%s)", exc)

    def __queue_growatt_forward(
        self,
        client_id: str,
        topic: str,
        payload: bytes,
        qos: int,
        retain: bool,
    ) -> None:
        key = f"forward_client_{client_id}"
        with self._forward_pending_lock:
            queue = self._forward_pending.setdefault(key, deque())
            if len(queue) >= 100:
                queue.popleft()
                if key not in self._forward_overflow_warned:
                    LOG.warning(
                        "%s: Growatt Cloud connection is delayed; oldest queued message was discarded",
                        _device_label(client_id),
                    )
                    self._forward_overflow_warned.add(key)
            queue.append((topic, bytes(payload), int(qos), bool(retain)))

    def __flush_growatt_forward_queue(self, client_id: str, client) -> None:
        key = f"forward_client_{client_id}"
        while True:
            with self._forward_pending_lock:
                queue = self._forward_pending.get(key)
                if not queue:
                    self._forward_pending.pop(key, None)
                    self._forward_overflow_warned.discard(key)
                    return
                topic, payload, qos, retain = queue[0]

            result = client.publish(
                topic,
                payload=payload,
                qos=qos,
                retain=retain,
            )
            status = getattr(result, "rc", None)
            if status is None:
                try:
                    status = result[0]
                except (TypeError, IndexError, KeyError):
                    status = None

            if status == mqtt.MQTT_ERR_NO_CONN:
                ready = self._forward_ready.get(key)
                if ready is not None:
                    ready.clear()
                return
            if status not in (None, mqtt.MQTT_ERR_SUCCESS):
                LOG.warning(
                    "Could not send an MQTT message to %s (error code %s)",
                    topic,
                    status,
                )
                return

            with self._forward_pending_lock:
                queue = self._forward_pending.get(key)
                if queue:
                    queue.popleft()

    def __publish_to_growatt_server(
        self,
        client_id: str,
        topic: str,
        payload: bytes,
        qos: int,
        retain: bool,
    ) -> None:
        client = self.__connect_to_growatt_server(client_id)
        key = f"forward_client_{client_id}"
        ready = self._forward_ready[key]

        if not ready.is_set():
            self.__queue_growatt_forward(client_id, topic, payload, qos, retain)
            return

        result = client.publish(topic, payload=payload, qos=qos, retain=retain)
        status = getattr(result, "rc", None)
        if status is None:
            try:
                status = result[0]
            except (TypeError, IndexError, KeyError):
                status = None

        if status == mqtt.MQTT_ERR_NO_CONN:
            ready.clear()
            self.__queue_growatt_forward(client_id, topic, payload, qos, retain)
            return
        if status not in (None, mqtt.MQTT_ERR_SUCCESS):
            LOG.warning("Could not send an MQTT message to %s (error code %s)", topic, status)

    # Setup Growatt MQTT broker for forwarding messages
    def __connect_to_growatt_server(self, client_id):
        key = f"forward_client_{client_id}"

        if key not in self._forward_clients:
            LOG.info(
                "%s: connecting to Growatt Cloud",
                _device_label(client_id),
            )
            client = mqtt.Client(
                client_id=client_id,
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            )
            client.tls_set(cert_reqs=ssl.CERT_NONE)
            client.tls_insecure_set(True)
            client.on_message = self.__on_message_forward_client

            ready = threading.Event()

            def on_connect(forward_client, _userdata, _flags, reason_code, _properties):
                if getattr(reason_code, "is_failure", False):
                    LOG.warning(
                        "%s: could not connect to Growatt Cloud (%s)",
                        _device_label(client_id),
                        reason_code,
                    )
                    return
                forward_client.subscribe(f"+/{client_id}")
                ready.set()
                self.__flush_growatt_forward_queue(client_id, forward_client)

            def on_disconnect(
                _forward_client,
                _userdata,
                _disconnect_flags,
                _reason_code,
                _properties,
            ):
                ready.clear()

            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            client.connect(
                self._forward_mqtt_config.host,
                self._forward_mqtt_config.port,
                60,
            )
            client.loop_start()
            self._forward_clients[key] = client
            self._forward_ready[key] = ready

        return self._forward_clients[key]


# Ensure that the dump directory exists
if DUMP_MESSAGES and not os.path.exists(DUMP_DIR):
    os.makedirs(DUMP_DIR, exist_ok=True)
    LOG.info("Dump directory created: %s", DUMP_DIR)


def dump_message_binary(topic, payload):
    """Compatibility entrypoint for the centralized raw MQTT JSONL dump."""
    dump_message_jsonl(DUMP_DIR, topic, payload)


def get_property(msg, prop) -> str | None:
    properties = getattr(msg, "properties", None)
    if properties is None:
        return None

    # Paho MQTT v5 exposes UserProperty directly. This avoids building a full
    # JSON representation for the common per-message forwarded-for check.
    user_properties = getattr(properties, "UserProperty", None)
    if isinstance(user_properties, (list, tuple)):
        for entry in user_properties:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            key, value = entry
            if key == prop:
                return value
        return None

    # Compatibility fallback for mocks/older property implementations.
    try:
        data = properties.json()
    except (AttributeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for entry in data.get("UserProperty", []) or []:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            continue
        key, value = entry
        if key == prop:
            return value
    return None
