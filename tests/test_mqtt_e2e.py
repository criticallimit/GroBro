import json
import os
import threading
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt
import pytest

from grobro import grobro, ha
from grobro.model.mqtt_config import MQTTConfig


DATA_DIR = Path(__file__).parent / "model" / "data"


def _wait_until(predicate, timeout=8.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.mark.skipif(
    not os.getenv("E2E_MQTT_HOST"),
    reason="requires a real MQTT broker (set E2E_MQTT_HOST)",
)
def test_real_mqtt_bidirectional_bridge(tmp_path, monkeypatch):
    """Exercise real Paho clients through a real broker in both directions."""
    host = os.environ["E2E_MQTT_HOST"]
    port = int(os.getenv("E2E_MQTT_PORT", "1883"))
    suffix = f"e2e-{uuid.uuid4().hex[:10]}"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MQTT_CLIENT_SUFFIX", suffix)

    broker = MQTTConfig(host=host, port=port)
    forward = MQTTConfig(host=host, port=port)

    received = {}
    received_lock = threading.Lock()
    probe_connected = threading.Event()

    probe = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"grobro-probe-{suffix}",
        protocol=mqtt.MQTTv5,
    )

    def on_probe_connect(client, userdata, flags, reason_code, properties):
        del userdata, flags, properties
        assert reason_code == 0
        client.subscribe("homeassistant/#")
        client.subscribe("s/#")
        probe_connected.set()

    def on_probe_message(client, userdata, message):
        del client, userdata
        with received_lock:
            received[message.topic] = bytes(message.payload)

    probe.on_connect = on_probe_connect
    probe.on_message = on_probe_message
    probe.connect(host, port, 60)

    ha_client = None
    grobro_client = None

    try:
        probe.loop_start()
        assert probe_connected.wait(5), "probe did not connect to MQTT broker"

        ha_client = ha.Client(broker)
        grobro_client = grobro.Client(broker, forward)

        grobro_client.on_input_register = ha_client.publish_input_register
        grobro_client.on_holding_register_input = ha_client.publish_holding_register_input
        grobro_client.on_config = ha_client.set_config
        grobro_client.on_config_read_response = ha_client.handle_config_read_response
        ha_client.on_command = grobro_client.send_command
        ha_client.on_config_read = grobro_client.send_config_read_message
        ha_client.on_config_command = (
            lambda dev, reg, val: grobro_client.send_config_message(dev, reg, val)
        )

        ha_client.start()
        grobro_client.start()

        assert _wait_until(
            lambda: ha_client._client.is_connected() and grobro_client._client.is_connected()
        ), "Better GroBro MQTT clients did not connect"

        # Allow the source client subscription to c/# to reach the broker.
        time.sleep(0.2)

        device_id = "QMN000ABC1D2E3FG"
        discovery_topic = f"homeassistant/device/{device_id}/config"
        state_topic = f"homeassistant/grobro/{device_id}/state"
        availability_topic = f"homeassistant/grobro/{device_id}/availability"
        command_topic = f"homeassistant/config/grobro/{device_id}/32/set"
        device_command_topic = f"s/33/{device_id}"

        config_payload = (DATA_DIR / "NeoConfigTLV_340.bin").read_bytes()
        info = probe.publish(f"c/33/{device_id}", config_payload, qos=1)
        info.wait_for_publish(timeout=5)

        assert _wait_until(
            lambda: discovery_topic in received and bool(received[discovery_topic])
        ), "real MQTT config packet did not produce HA discovery"

        discovery = json.loads(received[discovery_topic].decode())
        assert discovery["dev"]["identifiers"] == [device_id]
        assert "NEO" in discovery["dev"]["model"]
        restart = discovery["cmps"][f"grobro_{device_id}_restart_datalogger"]
        assert restart["command_topic"] == command_topic
        assert restart["payload_press"] == "1"

        telemetry_payload = (DATA_DIR / "NeoReadInputRegisters.bin").read_bytes()
        info = probe.publish(f"c/33/{device_id}", telemetry_payload, qos=1)
        info.wait_for_publish(timeout=5)

        assert _wait_until(lambda: state_topic in received), (
            "real MQTT telemetry did not produce a Home Assistant state message"
        )
        state = json.loads(received[state_topic].decode())
        assert isinstance(state, dict)
        assert state
        assert _wait_until(
            lambda: received.get(availability_topic) == b"online"
        ), "device was not marked online through the real MQTT path"

        # Exercise the opposite direction as well: HA command -> HA MQTT client
        # -> GroBro command builder -> source broker -> device command topic.
        with received_lock:
            received.pop(device_command_topic, None)

        info = probe.publish(command_topic, "1", qos=1)
        info.wait_for_publish(timeout=5)

        assert _wait_until(lambda: device_command_topic in received), (
            "HA MQTT command did not reach the device command topic"
        )
        assert received[device_command_topic], "device command payload must not be empty"
    finally:
        if ha_client is not None:
            for timer in list(getattr(ha_client, "_device_timers", {}).values()):
                timer.cancel()
            ha_client.stop()
        if grobro_client is not None:
            grobro_client.stop()
        probe.loop_stop()
        probe.disconnect()

@pytest.mark.skipif(
    not os.getenv("E2E_MQTT_HOST"),
    reason="requires a real MQTT broker (set E2E_MQTT_HOST)",
)
def test_real_mqtt_noah_bridge(tmp_path, monkeypatch):
    """Exercise NOAH config, telemetry and HA command paths through a real broker."""
    host = os.environ["E2E_MQTT_HOST"]
    port = int(os.getenv("E2E_MQTT_PORT", "1883"))
    suffix = f"e2e-noah-{uuid.uuid4().hex[:10]}"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MQTT_CLIENT_SUFFIX", suffix)

    broker = MQTTConfig(host=host, port=port)
    received = {}
    received_lock = threading.Lock()
    probe_connected = threading.Event()

    probe = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"grobro-probe-{suffix}",
        protocol=mqtt.MQTTv5,
    )

    def on_probe_connect(client, userdata, flags, reason_code, properties):
        del userdata, flags, properties
        assert reason_code == 0
        client.subscribe("homeassistant/#")
        client.subscribe("s/#")
        probe_connected.set()

    def on_probe_message(client, userdata, message):
        del client, userdata
        with received_lock:
            received[message.topic] = bytes(message.payload)

    probe.on_connect = on_probe_connect
    probe.on_message = on_probe_message
    probe.connect(host, port, 60)

    ha_client = None
    grobro_client = None

    try:
        probe.loop_start()
        assert probe_connected.wait(5), "probe did not connect to MQTT broker"

        ha_client = ha.Client(broker)
        grobro_client = grobro.Client(broker, broker)
        grobro_client.on_input_register = ha_client.publish_input_register
        grobro_client.on_holding_register_input = ha_client.publish_holding_register_input
        grobro_client.on_config = ha_client.set_config
        grobro_client.on_config_read_response = ha_client.handle_config_read_response
        ha_client.on_command = grobro_client.send_command
        ha_client.on_config_read = grobro_client.send_config_read_message
        ha_client.on_config_command = (
            lambda dev, reg, val: grobro_client.send_config_message(dev, reg, val)
        )

        ha_client.start()
        grobro_client.start()
        assert _wait_until(
            lambda: ha_client._client.is_connected() and grobro_client._client.is_connected()
        )
        time.sleep(0.2)

        device_id = "0PVP0000TEST0001"
        discovery_topic = f"homeassistant/device/{device_id}/config"
        state_topic = f"homeassistant/grobro/{device_id}/state"
        command_topic = f"homeassistant/config/grobro/{device_id}/32/set"
        device_command_topic = f"s/33/{device_id}"

        info = probe.publish(
            f"c/33/{device_id}",
            (DATA_DIR / "NoahTypeFE19_Config.bin").read_bytes(),
            qos=1,
        )
        info.wait_for_publish(timeout=5)

        assert _wait_until(
            lambda: discovery_topic in received and bool(received[discovery_topic])
        ), "NOAH config did not produce HA discovery through real MQTT"
        discovery = json.loads(received[discovery_topic].decode())
        assert discovery["dev"]["identifiers"] == [device_id]
        assert "NOAH" in discovery["dev"]["model"]

        info = probe.publish(
            f"c/33/{device_id}",
            (DATA_DIR / "NoahReadInputRegisters_0-124.bin").read_bytes(),
            qos=1,
        )
        info.wait_for_publish(timeout=5)

        assert _wait_until(lambda: state_topic in received), (
            "NOAH telemetry did not produce a Home Assistant state"
        )
        state = json.loads(received[state_topic].decode())
        assert state
        assert any(
            key in state
            for key in ("bat_1_soc_pct", "tot_bat_soc_pct", "out_power", "pv_tot_power")
        )

        with received_lock:
            received.pop(device_command_topic, None)
        info = probe.publish(command_topic, "1", qos=1)
        info.wait_for_publish(timeout=5)
        assert _wait_until(lambda: device_command_topic in received), (
            "NOAH HA command did not reach the device command topic"
        )
        assert received[device_command_topic]
    finally:
        if ha_client is not None:
            for timer in list(getattr(ha_client, "_device_timers", {}).values()):
                timer.cancel()
            ha_client.stop()
        if grobro_client is not None:
            grobro_client.stop()
        probe.loop_stop()
        probe.disconnect()

