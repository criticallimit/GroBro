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
from typing import Callable

import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessage

from grobro import model
from grobro.grobro import parser
from grobro.grobro.builder import append_crc, scramble
from grobro.model.growatt_registers import (
    KNOWN_MOD_REGISTERS,
    KNOWN_NEO_REGISTERS,
    KNOWN_NEXA_REGISTERS,
    KNOWN_NOAH_REGISTERS,
    KNOWN_SPF_REGISTERS,
    KNOWN_XH2_REGISTERS,
    HomeAssistantHoldingRegisterInput,
    HomeAssistantHoldingRegisterValue,
    HomeAssistantInputRegister,
)
from grobro.model.modbus_function import GrowattModbusFunctionSingle
from grobro.model.modbus_message import GrowattModbusFunction, GrowattModbusMessage
from grobro.model.mqtt_config import MQTTConfig


_DEVICE_ID_RE = re.compile(r"[^A-Za-z0-9]")
_FALSE_VALUES = {"", "false", "0", "no", "off"}


def _extract_device_id(topic: str) -> str:
    """Extract the device serial from the last segment of an MQTT topic.

    Growatt device serials are alphanumeric (A-Z, 0-9). Some dongles
    (e.g. ShineWiFi-X2 / XH family) include stray trailing bytes in the
    SUBSCRIBE topic, such as `s/33/ZGQ0F5601J?\\x18`. Strip everything
    that isn't a valid serial character.
    """
    return _DEVICE_ID_RE.sub("", str(topic).split("/")[-1])


def _known_registers_for_device(device_id: str):
    if device_id.startswith(("QMN", "RAQ", "PTQ")):
        return KNOWN_NEO_REGISTERS
    if device_id.startswith("0PVP"):
        return KNOWN_NOAH_REGISTERS
    if device_id.startswith("0HVR"):
        return KNOWN_NEXA_REGISTERS
    if device_id.startswith("HAQ"):
        return KNOWN_SPF_REGISTERS
    if device_id.startswith("ZGQ"):
        return KNOWN_XH2_REGISTERS
    if device_id.startswith("VWQ"):
        return KNOWN_MOD_REGISTERS
    return None


def _publish_checked(client, topic: str, payload=None, **kwargs):
    """Publish and warn when Paho rejects the request locally."""
    result = client.publish(topic, payload, **kwargs)
    status = getattr(result, "rc", None)
    if status is None:
        try:
            status = result[0]
        except (TypeError, IndexError, KeyError):
            status = None
    if status not in (None, 0):
        LOG.warning("MQTT publish failed for topic %s: rc=%s", topic, status)
    return result


LOG = logging.getLogger(__name__)
HA_BASE_TOPIC = os.getenv("HA_BASE_TOPIC", "homeassistant")

# Updated growatt cloud forwarding config.
# `false` must really mean disabled; any other non-boolean value is interpreted
# as a comma-separated device allowlist for backwards compatibility.
GROWATT_CLOUD = os.getenv("GROWATT_CLOUD", "false").strip()
GROWATT_CLOUD_CONFIG_FILTER = os.getenv("GROWATT_CLOUD_CONFIG_FILTER", "false").lower()
_cloud_lower = GROWATT_CLOUD.lower()
if _cloud_lower in _FALSE_VALUES:
    GROWATT_CLOUD_ENABLED = False
    GROWATT_CLOUD_FILTER = set()
elif _cloud_lower == "true":
    GROWATT_CLOUD_ENABLED = True
    GROWATT_CLOUD_FILTER = set()
else:
    GROWATT_CLOUD_ENABLED = True
    GROWATT_CLOUD_FILTER = {
        item.strip() for item in GROWATT_CLOUD.split(",") if item.strip()
    }

DUMP_MESSAGES = os.getenv("DUMP_MESSAGES", "false").lower() == "true"
PUBLISH_SENSORS_RETAINED = os.getenv("PUBLISH_SENSORS_RETAINED", "False").lower() == "true"
DUMP_DIR = os.getenv("DUMP_DIR", "/dump")

# Property to flag messages forwarded from growatt cloud
MQTT_PROP_FORWARD_GROWATT = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
MQTT_PROP_FORWARD_GROWATT.UserProperty = [("forwarded-for", "growatt")]

# Property to flag messages forwarded from ha
MQTT_PROP_FORWARD_HA = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
MQTT_PROP_FORWARD_HA.UserProperty = [("forwarded-for", "ha")]

# Property to flag messages as dry-run for debugging purposes
MQTT_PROP_DRY_RUN = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
MQTT_PROP_DRY_RUN.UserProperty = [("dry-run", "true")]


class Client:
    on_config: Callable[[str, model.DeviceConfig], None]
    on_input_register: Callable[HomeAssistantInputRegister, None]
    on_holding_register_input: Callable[HomeAssistantHoldingRegisterInput, None]

    _client: mqtt.Client
    _forward_mqtt_config: model.MQTTConfig

    def __init__(self, grobro_mqtt: MQTTConfig, forward_mqtt: MQTTConfig):
        LOG.info(
            "Connecting to GroBro broker at '%s:%s'",
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
        self._ptq_for_raq: dict[str, str] = {}

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
        header = b"\x00\x01\x00\x07"
        msg_type = 0x0119

        dev = device_id.encode("ascii").ljust(16, b"\x00")
        body = struct.pack(">HH", 1, register_no)
        payload = b"\x00" * 14 + body
        msg_len = len(payload) + 18

        msg = (
            header
            + struct.pack(">H", msg_len)
            + struct.pack(">H", msg_type)
            + dev
            + payload
        )

        final_payload = append_crc(scramble(msg))
        topic = f"s/33/{device_id}"

        LOG.info("Sending config read to %s register=%s", device_id, register_no)
        return _publish_checked(
            self._client,
            topic,
            final_payload,
            properties=MQTT_PROP_FORWARD_HA,
        )

    def send_config_message(self, device_id: str, register_no: int, value: str):
        header = b"\x00\x01\x00\x07"
        msg_type = 0x0118
        dev = device_id.encode("ascii").ljust(16, b"\x00")
        value_bytes = str(value).encode("ascii")

        tlv = (
            struct.pack(">H", 1)
            + struct.pack(">H", len(value_bytes) + 4)
            + struct.pack(">H", register_no)
            + struct.pack(">H", len(value_bytes))
            + value_bytes
        )
        payload = b"\x00" * 14 + tlv
        msg_len = len(payload) + 18

        raw = (
            header
            + struct.pack(">H", msg_len)
            + struct.pack(">H", msg_type)
            + dev
            + payload
        )
        final_payload = append_crc(scramble(raw))

        topic = f"s/33/{device_id}"
        # Never log the value: config registers can contain credentials.
        LOG.info("Sending config message to %s register=%s", device_id, register_no)
        return _publish_checked(
            self._client,
            topic,
            final_payload,
            properties=MQTT_PROP_FORWARD_HA,
        )

    def __on_connect(self, client, userdata, flags, reason_code, properties):
        LOG.debug("Connected to GroBro MQTT server with result code %s", reason_code)
        client.subscribe("c/#")

    def __on_message(self, client, userdata, msg: MQTTMessage):
        # check for forwarded messages and ignore them
        forwarded_for = get_property(msg, "forwarded-for")
        if forwarded_for in {"ha", "growatt"}:
            LOG.debug("Message forwarded from %s. Skipping...", forwarded_for)
            return

        file_name = get_property(msg, "file")
        LOG.debug("Received message (%s): %s: %s", file_name, msg.topic, msg.payload)
        if DUMP_MESSAGES:
            dump_message_binary(msg.topic, msg.payload)
        try:
            device_id = _extract_device_id(msg.topic)
            if not device_id:
                LOG.debug("Ignoring MQTT message without a usable device id: %s", msg.topic)
                return

            if GROWATT_CLOUD_ENABLED and (
                _cloud_lower == "true" or device_id in GROWATT_CLOUD_FILTER
            ):
                try:
                    forward_client = self.__connect_to_growatt_server(device_id)
                    _publish_checked(
                        forward_client,
                        msg.topic,
                        payload=msg.payload,
                        qos=msg.qos,
                        retain=msg.retain,
                    )
                except Exception as exc:
                    LOG.error("Forwarding to Growatt Cloud failed: %s", exc)

            unscrambled = parser.unscramble(msg.payload)
            if len(unscrambled) < 8:
                LOG.debug("Ignoring truncated Growatt message for %s", device_id)
                return
            LOG.debug("Received: %s %s", msg.topic, unscrambled.hex(" "))

            # Read msg_type from both possible offsets
            msg_type_4 = struct.unpack_from(">H", unscrambled, 4)[0]
            msg_type = struct.unpack_from(">H", unscrambled, 6)[0]

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
                    LOG.info("Received config message for %s", device_id)
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
                                "Registered PTQ inverter %s behind %s",
                                ptq_serial,
                                device_id,
                            )
                return

            # Config READ response (281)
            if msg_type == 281:
                cfg = parser.parse_config_message(unscrambled)
                LOG.info(
                    "Received config read response for %s reg=%s",
                    cfg["device_id"],
                    cfg["register_no"],
                )

                topic = (
                    f"{HA_BASE_TOPIC}/config/grobro/"
                    f"{cfg['device_id']}/{cfg['register_no']}/get"
                )
                value = cfg["value"]

                known_registers = _known_registers_for_device(cfg["device_id"])
                if known_registers:
                    for reg in known_registers.config_registers.values():
                        if reg.growatt.register_no == cfg["register_no"]:
                            if reg.growatt.data.data_type == "INT":
                                try:
                                    value = int(value)
                                except (TypeError, ValueError):
                                    LOG.debug(
                                        "Invalid integer config value for %s reg=%s",
                                        cfg["device_id"],
                                        cfg["register_no"],
                                    )
                                    return
                            break

                _publish_checked(self._client, topic, value, retain=True)

                if self.on_config_read_response:
                    self.on_config_read_response(
                        cfg["device_id"],
                        cfg["register_no"],
                    )
                return

            # Config WRITE response (280)
            if msg_type == 280:
                cfg = parser.parse_config_ack(unscrambled)
                LOG.info(
                    "Received config write response for %s reg=%s accepted",
                    cfg["device_id"],
                    cfg["register_no"],
                )
                return

            # NOAH/NEXA Smart Meter (EcoTracker, Shelly etc.) JSON data (0x6F64)
            if msg_type == 0x6F64:
                smart_meter = parser.parse_noah_6f64(unscrambled)
                LOG.debug(
                    "Smart Meter data for %s: %s",
                    smart_meter["device_id"],
                    smart_meter["data"],
                )
                topic = (
                    f"{HA_BASE_TOPIC}/sensor/grobro/"
                    f"{smart_meter['device_id']}/smart_meter/state"
                )
                _publish_checked(
                    self._client,
                    topic,
                    smart_meter["data"],
                    retain=PUBLISH_SENSORS_RETAINED,
                )
                return

            # NOAH/NEXA-specific message types (FE19 config, 0103 holding regs, etc.)
            noah_msg = parser.parse_noah_message(unscrambled)
            if noah_msg and noah_msg.get("message_type") == 0xFE19:
                if device_id.startswith(("0PVP", "0HVR")):
                    config = noah_msg.get("config")
                    if config and config.serial_number:
                        LOG.info(
                            "Received config for %s (sw_version=%s)",
                            config.serial_number,
                            config.sw_version or "?",
                        )
                        self.on_config(device_id, config)
                        return

            # Generic modbus message
            modbus_message = GrowattModbusMessage.parse_grobro(unscrambled)
            LOG.debug("Received modbus message: %s", modbus_message)

            if modbus_message:
                ptq_device_id = self._ptq_for_raq.get(device_id)
                modbus_device_id = ptq_device_id or device_id
                known_registers = _known_registers_for_device(modbus_device_id)
                if not known_registers:
                    LOG.info("Modbus message from unknown device type: %s", device_id)
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
                    if state.payload:
                        self.on_input_register(state)
                    return

                return

            LOG.debug("Unknown msg_type %s: %s", msg_type, unscrambled.hex())
        except (struct.error, TypeError, ValueError, KeyError) as exc:
            LOG.error("Processing malformed message from %s: %s", msg.topic, exc)
        except Exception as exc:
            LOG.exception("Unexpected error processing message from %s: %s", msg.topic, exc)

    def __on_message_forward_client(self, client, userdata, msg: MQTTMessage):
        LOG.debug("Received Growatt forward message: %s: %s", msg.topic, msg.payload)
        if DUMP_MESSAGES:
            dump_message_binary(msg.topic, msg.payload)
        try:
            device_id = _extract_device_id(msg.topic)
            if not device_id:
                return

            unscrambled = parser.unscramble(msg.payload)
            if len(unscrambled) < 8:
                LOG.debug("Ignoring truncated Growatt cloud message for %s", device_id)
                return
            LOG.debug("Received Growatt forward: %s %s", msg.topic, unscrambled.hex(" "))

            if not GROWATT_CLOUD_ENABLED:
                return
            if _cloud_lower != "true" and device_id not in GROWATT_CLOUD_FILTER:
                LOG.debug(
                    "Dropping Growatt message for device %s not in GROWATT_CLOUD filter",
                    device_id,
                )
                return

            # Cloud configuration filtering belongs in the Cloud -> device path.
            if GROWATT_CLOUD_CONFIG_FILTER == "true":
                cloud_msg_type = struct.unpack_from(">H", unscrambled, 6)[0]
                if cloud_msg_type in (0x0118, 0x0110):
                    LOG.warning(
                        "Blocked configuration command from Growatt Cloud for %s",
                        device_id,
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
            LOG.error("Forwarding malformed Growatt message: %s", exc)
        except Exception as exc:
            LOG.exception("Unexpected Growatt forwarding error: %s", exc)

    # Setup Growatt MQTT broker for forwarding messages
    def __connect_to_growatt_server(self, client_id):
        key = f"forward_client_{client_id}"
        if key not in self._forward_clients:
            LOG.info(
                "Connecting to Growatt broker at '%s:%s', subscribed to '+/%s'",
                self._forward_mqtt_config.host,
                self._forward_mqtt_config.port,
                client_id,
            )
            client = mqtt.Client(
                client_id=client_id,
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            )
            client.tls_set(cert_reqs=ssl.CERT_NONE)
            client.tls_insecure_set(True)
            client.on_message = self.__on_message_forward_client
            client.connect(
                self._forward_mqtt_config.host,
                self._forward_mqtt_config.port,
                60,
            )
            client.subscribe(f"+/{client_id}")
            client.loop_start()
            self._forward_clients[key] = client
        return self._forward_clients[key]


# Ensure that the dump directory exists
if DUMP_MESSAGES and not os.path.exists(DUMP_DIR):
    os.makedirs(DUMP_DIR, exist_ok=True)
    LOG.info("Dump directory created: %s", DUMP_DIR)


def dump_message_binary(topic, payload):
    """Legacy dump hook; replaced by cleanup hook in the HA bridge."""
    try:
        topic_parts = [part for part in str(topic).strip("/").split("/") if part]
        if not topic_parts:
            topic_parts = ["_"]
        safe_parts = [re.sub(r"[^A-Za-z0-9._-]+", "_", part).strip(".") or "_" for part in topic_parts]
        root = os.path.abspath(DUMP_DIR)
        dir_path = os.path.abspath(os.path.join(root, *safe_parts))
        if os.path.commonpath([root, dir_path]) != root:
            raise ValueError("dump path escaped DUMP_DIR")
        os.makedirs(dir_path, exist_ok=True)
        file_path = os.path.join(dir_path, f"{int(__import__('time').time() * 1000)}.bin")
        with open(file_path, "wb") as handle:
            handle.write(bytes(payload))
    except (OSError, TypeError, ValueError) as exc:
        LOG.error("Failed to dump message for topic %s: %s", topic, exc)


def get_property(msg, prop) -> str | None:
    properties = getattr(msg, "properties", None)
    if properties is None:
        return None
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
