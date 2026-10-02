import json
import os
import threading
import time
import uuid
import subprocess
import sys
from pathlib import Path

import paho.mqtt.client as mqtt
import pytest

from grobro import grobro, ha
from grobro.model.mqtt_config import MQTTConfig
from grobro.ha_bridge import wire_clients


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

        wire_clients(ha_client, grobro_client)

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
@pytest.mark.parametrize("username,password", [(None, None), ("e2e-user", "")])
def test_real_mqtt_noah_bridge(tmp_path, monkeypatch, username, password):
    """Exercise NOAH config, telemetry and HA command paths through a real broker."""
    host = os.environ["E2E_MQTT_HOST"]
    port = int(os.getenv("E2E_MQTT_PORT", "1883"))
    suffix = f"e2e-noah-{uuid.uuid4().hex[:10]}"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MQTT_CLIENT_SUFFIX", suffix)

    broker = MQTTConfig(host=host, port=port, username=username, password=password)
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
        wire_clients(ha_client, grobro_client)

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



@pytest.mark.skipif(
    not os.getenv("E2E_MQTT_TARGET_PORT"),
    reason="requires two separate real MQTT brokers (set E2E_MQTT_TARGET_PORT)",
)
def test_separate_brokers_readback_smart_meter_and_shutdown(tmp_path, monkeypatch):
    host = os.environ["E2E_MQTT_HOST"]
    source_port = int(os.environ["E2E_MQTT_PORT"])
    target_port = int(os.environ["E2E_MQTT_TARGET_PORT"])
    assert source_port != target_port
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MQTT_CLIENT_SUFFIX", "split-" + uuid.uuid4().hex[:10])
    seen = [{}, {}]
    probes = []
    target = source = None
    try:
        for index, port in enumerate((source_port, target_port)):
            probe = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
            ready = threading.Event()
            probe.on_connect = lambda client, *_args, event=ready: (
                client.subscribe([("homeassistant/#", 1), ("s/#", 1)]), event.set()
            )
            probe.on_message = lambda client, userdata, msg, bucket=seen[index]: bucket.update({msg.topic: bytes(msg.payload)})
            probe.connect(host, port, 60)
            probe.loop_start()
            probes.append(probe)
            assert ready.wait(5)
        target_cfg = MQTTConfig(host=host, port=target_port)
        source_cfg = MQTTConfig(host=host, port=source_port)
        target = ha.Client(target_cfg)
        source = grobro.Client(source_cfg, source_cfg)
        wire_clients(target, source)
        target.start()
        source.start()
        assert _wait_until(lambda: target._client.is_connected() and source._client.is_connected())
        time.sleep(0.2)
        config = (DATA_DIR / "NeoConfigReadResponse_337.bin").read_bytes()
        info = probes[0].publish("c/33/QMN000ABC1D2E3FG", config, qos=1)
        info.wait_for_publish(timeout=5)
        readback_prefix = "homeassistant/config/grobro/QMN000ABC1D2E3FG/"
        assert _wait_until(lambda: any(key.startswith(readback_prefix) for key in seen[1]))
        assert not any(key.startswith(readback_prefix) for key in seen[0])

        # Build the same smart-meter wire format as the parser's captured cases.
        from grobro.grobro.builder import scramble, append_crc
        device = "0PVPTEST123456789"
        body = b'{"t_act":150}'
        data = bytearray(79 + len(body))
        data[0:4] = b"\x00\x01\x00\x07"
        data[4:6] = (len(data) + 2).to_bytes(2, "big")
        data[6:8] = b"\x6f\x64"
        data[8:38] = device.encode().ljust(30, b"\x00")
        data[38:68] = b"meter".ljust(30, b"\x00")
        data[68:75] = bytes([26, 5, 15, 17, 12, 9, 1])
        data[75:79] = len(body).to_bytes(4, "big")
        data[79:] = body
        packet = append_crc(scramble(bytes(data)))
        smart_topic = f"homeassistant/sensor/grobro/{device}/smart_meter/state"
        probes[0].publish(f"c/33/{device}", packet, qos=1).wait_for_publish(timeout=5)
        assert _wait_until(lambda: seen[1].get(smart_topic) == body)
        assert smart_topic not in seen[0]
        seen[1].pop(smart_topic)
        probes[1].publish("homeassistant/status", "online", qos=1).wait_for_publish(timeout=5)
        assert _wait_until(lambda: not target._smart_meter_state_cache)
        probes[0].publish(f"c/33/{device}", packet, qos=1).wait_for_publish(timeout=5)
        assert _wait_until(lambda: seen[1].get(smart_topic) == body)

        command_topic = "homeassistant/switch/grobro/QMN000ABC1D2E3FG/inverter_power/set"
        probes[1].publish(command_topic, b"\xff", qos=1).wait_for_publish(timeout=5)
        probes[1].publish(command_topic, "ON", qos=1).wait_for_publish(timeout=5)
        assert _wait_until(lambda: "s/33/QMN000ABC1D2E3FG" in seen[0])
        bridge_topic = target._bridge_availability_topic
        target.stop()
        assert _wait_until(lambda: seen[1].get(bridge_topic) == b"offline")
    finally:
        if target is not None:
            target.stop()
        if source is not None:
            source.stop()
        for probe in probes:
            probe.disconnect()
            probe.loop_stop()


@pytest.mark.skipif(not os.getenv("E2E_MQTT_HOST"), reason="requires a real MQTT broker")
def test_bridge_last_will_on_abrupt_process_exit(tmp_path):
    host = os.environ["E2E_MQTT_HOST"]
    port = int(os.environ["E2E_MQTT_PORT"])
    suffix = "will-" + uuid.uuid4().hex[:10]
    topic = f"homeassistant/grobro/grobro-ha-{suffix}/availability"
    received = []
    ready = threading.Event()
    probe = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    probe.on_connect = lambda client, *_: (client.subscribe(topic, qos=1), ready.set())
    probe.on_message = lambda client, userdata, msg: received.append(bytes(msg.payload))
    probe.connect(host, port, 60)
    child = None
    try:
        probe.loop_start()
        assert ready.wait(5)
        env = os.environ.copy()
        env["MQTT_CLIENT_SUFFIX"] = suffix
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        code = (
            "import time; from grobro import ha; from grobro.model.mqtt_config import MQTTConfig; "
            f"client=ha.Client(MQTTConfig(host={host!r}, port={port})); client.start(); time.sleep(60)"
        )
        child = subprocess.Popen([sys.executable, "-c", code], cwd=tmp_path, env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert _wait_until(lambda: b"online" in received)
        child.kill()
        child.wait(timeout=5)
        assert _wait_until(lambda: received[-1:] == [b"offline"])
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        probe.disconnect()
        probe.loop_stop()


@pytest.mark.skipif(not os.getenv("E2E_MQTT_HOST"), reason="requires real MQTT brokers")
def test_real_cloud_async_forwarding_and_reconnect(tmp_path, monkeypatch):
    """Cloud transport preserves queued bytes/order across a real lost socket."""
    import socket
    host = os.environ["E2E_MQTT_HOST"]
    port = int(os.getenv("E2E_MQTT_PORT", "1883"))
    forward_port = int(os.getenv("E2E_MQTT_TARGET_PORT", str(port)))
    monkeypatch.chdir(tmp_path)
    # Local test brokers are plaintext; production TLS setup remains exercised by unit tests.
    monkeypatch.setattr(mqtt.Client, "tls_set", lambda *args, **kwargs: None)
    monkeypatch.setattr(mqtt.Client, "tls_insecure_set", lambda *args, **kwargs: None)
    device = "QMN" + uuid.uuid4().hex[:10].upper()
    topic = f"c/33/{device}"
    probe = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    subscribed = threading.Event()
    received = []
    probe.on_connect = lambda client, *args: client.subscribe(topic)
    probe.on_subscribe = lambda *args: subscribed.set()
    probe.on_message = lambda client, userdata, message: received.append(bytes(message.payload))
    source = None
    try:
        probe.connect(host, forward_port, 60)
        probe.loop_start()
        assert subscribed.wait(5)
        source = grobro.Client(MQTTConfig(host=host, port=port), MQTTConfig(host=host, port=forward_port))
        source._Client__publish_to_growatt_server(device, topic, b"first", 0, False)
        assert _wait_until(lambda: received == [b"first"])
        forward = source._forward_clients[f"forward_client_{device}"]
        disconnected = threading.Event()
        original = forward.on_disconnect
        def on_disconnect(*args):
            original(*args)
            disconnected.set()
        forward.on_disconnect = on_disconnect
        forward.socket().shutdown(socket.SHUT_RDWR)
        assert disconnected.wait(5)
        source._Client__publish_to_growatt_server(device, topic, b"second", 0, False)
        source._Client__publish_to_growatt_server(device, topic, b"third", 0, False)
        assert _wait_until(lambda: received == [b"first", b"second", b"third"])
        assert not source._forward_pending
    finally:
        if source is not None:
            source.stop()
        probe.disconnect()
        probe.loop_stop()
