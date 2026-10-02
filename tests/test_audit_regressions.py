"""Regression coverage for the repository audit's state/identity failures."""
import json
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from grobro import grobro, ha, model
from grobro.ha.battery_position import (
    EMPTY_ASSIGNMENT, save_manual_assignments, stabilize_battery_payload,
)
from grobro.ha.cleanup import clear_reconnect_caches
from grobro.ha.supervisor_config import normalize_options
from grobro.model.growatt_registers import (
    HomeAssistantHoldingRegisterInput, HomeAssistantHoldingRegisterValue,
    HomeAssistantInputRegister,
)
from grobro.model.modbus_function import GrowattModbusFunctionSingle

DEVICE = "QMN000ABC1D2E3FG"


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("paho.mqtt.client.Client") as factory:
        factory.side_effect = [MagicMock(), MagicMock()]
        cfg = model.MQTTConfig(host="localhost", port=1883)
        target = ha.Client(cfg)
        source = grobro.Client(cfg, cfg)
    target._client.publish.return_value = (0, None)
    source._client.publish.return_value = (0, None)
    target.on_command = MagicMock(return_value=(0, None))
    target.on_config_read = MagicMock()
    yield target, source
    target.stop()
    source.stop()


def message(topic, payload):
    return SimpleNamespace(topic=topic, payload=payload)


@pytest.mark.parametrize("failure", [RuntimeError("readback failed"), OSError("offline")])
@pytest.mark.parametrize("write_result,expected", [((0, None), True), ((4, None), False)])
def test_neo_accepted_switch_fallback_survives_readback_failure(clients, failure, write_result, expected):
    target, _ = clients
    target.on_command.side_effect = [write_result, failure]
    with patch("grobro.ha.neo_power_runtime._publish_retained_switch_state") as publish:
        target._Client__on_message(target._client, None, message(
            f"homeassistant/switch/grobro/{DEVICE}/inverter_power/set", b"ON"
        ))
        assert target.on_command.call_count == 2
        if expected:
            publish.assert_called_once_with(target, DEVICE, "ON")
        else:
            publish.assert_not_called()


def test_manual_remap_keeps_cell_voltages_and_ignores_empty_destination(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_manual_assignments("0PVPTEST", {"3": "SN00200000000001"})
    remapped, _ = stabilize_battery_payload(SimpleNamespace(), "0PVPTEST", {
        "bat2_ser_part_1": "SN00200000000001", "battery2SOC": 42, "battery3SOC": 0,
        "maxcvbat2": 3.5, "mincvbat2": 3.2, "maxcvbat3": 0, "mincvbat3": 0,
    }, use_stable_auto=False)
    assert remapped["battery3SOC"] == 42
    assert remapped["maxcvbat3"] == 3.5
    assert remapped["mincvbat3"] == 3.2
    assert "maxcvbat2" not in remapped


def test_reserved_empty_battery_slot_drops_values_without_identity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_manual_assignments("0PVPTEST", {"2": EMPTY_ASSIGNMENT})
    remapped, _ = stabilize_battery_payload(SimpleNamespace(), "0PVPTEST", {
        "bat2_temp": 24, "battery2SOC": 42, "maxcvbat2": 3.5, "Ppv": 10,
    })
    assert remapped == {"Ppv": 10}


def test_incomplete_serial_fragments_do_not_create_persistent_identity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = SimpleNamespace()
    stabilize_battery_payload(client, "0PVPTEST", {
        "bat2_ser_part_1": "ABCD", "bat2_ser_part_2": "EFGH", "battery2SOC": 42,
    })
    assert not client._battery_position_maps
    assert not Path("battery_positions.json").exists()
    stabilize_battery_payload(client, "0PVPTEST", {
        f"bat2_ser_part_{i}": part
        for i, part in enumerate(("ABCD", "EFGH", "IJKL", "MNOP"), 1)
    })
    assert client._battery_position_maps["0PVPTEST"] == {"ABCDEFGHIJKLMNOP": 2}


@pytest.mark.parametrize("topic,payload", [
    (f"number/grobro/{DEVICE}/set_wirk/set", b"not-a-number"),
    (f"switch/grobro/{DEVICE}/inverter_power/set", b"maybe"),
    (f"switch/grobro/{DEVICE}/inverter_power/set", b"\xff"),
    (f"config/grobro/{DEVICE}/invalid/set", b"1"),
])
def test_malformed_command_does_not_break_next_valid_command(clients, topic, payload):
    target, _ = clients
    target._client.on_message(None, None, message("homeassistant/" + topic, payload))
    target.on_command.assert_not_called()
    target._client.on_message(None, None, message(
        f"homeassistant/switch/grobro/{DEVICE}/inverter_power/set", b"ON",
    ))
    assert target.on_command.call_count == 2


def test_runtime_only_changes_persist_and_ip_invalidates_discovery(clients):
    target, _ = clients
    target.set_config(DEVICE, model.DeviceConfig(serial_number=DEVICE, data_interval="1", local_ip="192.0.2.1"))
    target._client.publish.reset_mock()
    target.set_config(DEVICE, model.DeviceConfig(data_interval="5"))
    assert not any(c.args[0] == f"homeassistant/device/{DEVICE}/config" for c in target._client.publish.call_args_list)
    target.set_config(DEVICE, model.DeviceConfig(local_ip="192.0.2.2"))
    assert model.DeviceConfig.from_file(f"config_{DEVICE}.json").data_interval == "5"
    assert model.DeviceConfig.from_file(f"config_{DEVICE}.json").local_ip == "192.0.2.2"
    with patch("paho.mqtt.client.Client"):
        restored = ha.Client(model.MQTTConfig(host="localhost", port=1883))
    assert restored._config_cache[DEVICE].data_interval == "5"
    assert restored._config_cache[DEVICE].local_ip == "192.0.2.2"
    configs = [json.loads(c.args[1]) for c in target._client.publish.call_args_list
               if c.args[0] == f"homeassistant/device/{DEVICE}/config" and c.args[1]]
    assert "192.0.2.2" in json.dumps(configs[-1])
    restored.stop()


def holding(value):
    return HomeAssistantHoldingRegisterInput(device_id=DEVICE, payload=[
        HomeAssistantHoldingRegisterValue(name="inverter_power", value=value,
            register=model.get_known_registers(DEVICE).holding_registers["inverter_power"].homeassistant),
    ])


def test_real_readback_corrects_optimistic_state_and_rejected_write(clients):
    target, _ = clients
    target.publish_holding_register_input(holding("ON"))
    cmd = message(f"homeassistant/switch/grobro/{DEVICE}/inverter_power/set", b"OFF")
    target._client.on_message(None, None, cmd)
    target.publish_holding_register_input(holding("ON"))
    states = [c.args[1] for c in target._client.publish.call_args_list
              if c.args[0].endswith("/inverter_power/get")]
    assert states == ["ON", "OFF", "ON"]
    target._client.publish.reset_mock()
    target.on_command.return_value = (4, None)
    target._client.on_message(None, None, cmd)
    assert not any(c.args[0].endswith("/inverter_power/get") for c in target._client.publish.call_args_list)


@pytest.mark.parametrize("kind", ["telemetry", "holding", "availability", "smart_meter", "discovery"])
def test_failed_publish_is_retried_for_identical_data(clients, kind):
    target, _ = clients
    actions = {
        "telemetry": lambda: target.publish_input_register(HomeAssistantInputRegister(device_id=DEVICE, payload={"Ppv": 100})),
        "holding": lambda: target.publish_holding_register_input(holding("ON")),
        "availability": lambda: target._Client__publish_availability(DEVICE, True),
        "smart_meter": lambda: target.publish_smart_meter("0PVPTEST", '{"power":1}'),
        "discovery": lambda: target._Client__publish_device_discovery(DEVICE),
    }
    target._client.publish.return_value = (4, None)
    actions[kind]()
    target._client.publish.reset_mock()
    target._client.publish.return_value = (0, None)
    actions[kind]()
    assert target._client.publish.called
    if kind == "telemetry":
        assert any(c.args[0].endswith("/state") for c in target._client.publish.call_args_list)
    if kind == "discovery":
        assert DEVICE in target._discovery_cache


def test_smart_meter_republished_after_recovery(clients):
    target, _ = clients
    target.publish_smart_meter("0PVPTEST", '{"power":1}')
    target.publish_smart_meter("0PVPTEST", '{"power":1}')
    def state_count():
        return sum(call.args[0].endswith("/smart_meter/state") for call in target._client.publish.call_args_list)
    assert state_count() == 1
    clear_reconnect_caches(target)
    target.publish_smart_meter("0PVPTEST", '{"power":1}')
    assert state_count() == 2


@pytest.mark.parametrize("availability_failure", [False, True])
def test_unchanged_smart_meter_refreshes_device_timeout(clients, availability_failure):
    target, _ = clients
    with patch.object(target, "_Client__reset_device_timer") as timeout, patch.object(
        target, "_Client__publish_availability"
    ) as availability:
        if availability_failure:
            availability.side_effect = OSError("MQTT unavailable")
        target.publish_smart_meter("0PVPTEST", '{"power":1}')
        target.publish_smart_meter("0PVPTEST", '{"power":1}')
        assert timeout.call_count == 2
        assert availability.call_count == 2
        assert target._client.publish.call_count == 1


def test_fast_config_response_keeps_next_read_timer(clients):
    target, _ = clients
    target._config_read_queues[DEVICE] = deque([4, 5])
    target.on_config_read.side_effect = lambda device, reg: (
        target.handle_config_read_response(device, reg) if reg == 4 else None
    )
    with patch("grobro.ha.client.Timer") as timers:
        first, second = MagicMock(), MagicMock()
        timers.side_effect = [first, second]
        target._Client__kickoff_next_config_read(DEVICE)
    first.cancel.assert_called_once()
    assert target._config_read_inflight[DEVICE] == 5
    assert target._config_read_timers[DEVICE] is second
    assert target.on_config_read.call_count == 2


def test_stopped_runtime_cannot_schedule_or_publish(clients):
    target, _ = clients
    pending = MagicMock()
    target._read_all_start_timers[DEVICE] = pending
    target._config_read_queues[DEVICE] = deque([4])
    target.stop()
    pending.cancel.assert_called_once()
    target._client.publish.reset_mock()
    with patch("grobro.ha.client.Timer") as timers:
        target._Client__kickoff_next_config_read(DEVICE)
        target._Client__config_read_timeout(DEVICE, 4)
        target.handle_config_read_response(DEVICE, 4)
        target.publish_smart_meter("0PVPTEST", "{}")
    timers.assert_not_called()
    target._client.publish.assert_not_called()
    assert not target._config_read_queues


def test_gateway_identity_survives_restart_and_routes_only_modbus_to_endpoint(clients):
    _, source = clients
    source._remember_gateway("RAQ0TEST01", "PTQ0TEST1234567")
    with patch("paho.mqtt.client.Client"):
        cfg = model.MQTTConfig(host="localhost", port=1883)
        restarted = grobro.Client(cfg, cfg)
    assert restarted._ptq_for_raq["RAQ0TEST01"] == "PTQ0TEST1234567"
    cmd = GrowattModbusFunctionSingle(device_id="RAQ0TEST01", function=3, register=0, value=0)
    restarted.send_command(cmd)
    assert restarted._client.publish.call_args.args[0] == "s/33/PTQ0TEST1234567"
    assert cmd.device_id == "RAQ0TEST01"
    restarted.send_config_read_message("RAQ0TEST01", 4)
    assert restarted._client.publish.call_args.args[0] == "s/33/RAQ0TEST01"
    restarted.stop()


def test_password_whitespace_survives_normalization():
    options = normalize_options({"SOURCE_MQTT_PASS": " secret ", "TARGET_MQTT_PASS": " x "})
    assert options["SOURCE_MQTT_PASS"] == " secret "
    assert options["TARGET_MQTT_PASS"] == " x "


def test_secret_config_readback_clears_retained_password(clients):
    target, _ = clients
    target.publish_config_register_value(DEVICE, 7, "secret")
    target._client.publish.assert_called_once_with(
        f"homeassistant/config/grobro/{DEVICE}/7/get", "", retain=True,
    )


def test_stop_disconnects_even_if_offline_publish_raises(clients):
    target, _ = clients
    target._client.publish.side_effect = RuntimeError("network unavailable")
    with pytest.raises(RuntimeError):
        target.stop()
    target._client.disconnect.assert_called_once()
    target._client.loop_stop.assert_called_once()
    target._client.publish.side_effect = None


def test_gateway_without_endpoint_does_not_send_misaddressed_modbus(clients):
    _, source = clients
    cmd = GrowattModbusFunctionSingle(device_id="RAQUNKNOWN", function=3, register=0, value=0)
    assert source.send_command(cmd)[0] != 0
    source._client.publish.assert_not_called()


def test_unknown_family_has_consistent_empty_rules():
    from grobro.ha.performance import _register_rules
    assert len(_register_rules(None)) == 4


def test_cloud_connection_becoming_ready_during_enqueue_flushes_packet(clients):
    import threading
    _, source = clients
    forward = MagicMock()
    forward.publish.return_value = (0, None)
    source._forward_ready["forward_client_0PVPTEST"] = ready = threading.Event()
    original_queue = source._Client__queue_growatt_forward

    def queue_and_complete_connect(*args):
        original_queue(*args)
        ready.set()

    with patch.object(source, "_Client__connect_to_growatt_server", return_value=forward), \
         patch.object(source, "_Client__queue_growatt_forward", side_effect=queue_and_complete_connect):
        source._Client__publish_to_growatt_server("0PVPTEST", "c/0PVPTEST", b"packet", 1, False)
    forward.publish.assert_called_once_with("c/0PVPTEST", payload=b"packet", qos=1, retain=False)
    assert not source._forward_pending


@pytest.mark.parametrize("failure", ["start", "stop"])
def test_bridge_stops_both_clients_after_lifecycle_failure(failure):
    from grobro.ha_bridge import run_clients
    target, source, signal = MagicMock(), MagicMock(), MagicMock()
    getattr(target, failure).side_effect = RuntimeError("lifecycle failure")
    with pytest.raises(RuntimeError):
        run_clients(target, source, signal)
    target.stop.assert_called_once()
    source.stop.assert_called_once()


@pytest.mark.parametrize("stage", ["kickoff", "response"])
@pytest.mark.parametrize("failure", ["construct", "start"])
@pytest.mark.parametrize("error", [RuntimeError, OSError])
def test_read_all_timer_failure_cleans_sequence_and_allows_retry(clients, stage, failure, error):
    target, _ = clients
    request = message(f"homeassistant/button/grobro/{DEVICE}/read_all/press", b"")
    broken = MagicMock()
    with patch("grobro.ha.client.Timer", return_value=broken) as timers:
        if failure == "construct":
            timers.side_effect = error("threads unavailable")
        else:
            broken.start.side_effect = error("threads unavailable")
        if stage == "kickoff":
            target._Client__on_message(target._client, None, request)
        else:
            target._read_all_active.add(DEVICE)
            target._config_read_queues[DEVICE] = deque([4, 5])
            with pytest.raises(error):
                target._Client__kickoff_next_config_read(DEVICE)
    assert DEVICE not in target._config_read_queues
    assert DEVICE not in target._config_read_inflight
    assert DEVICE not in target._config_read_timers
    assert DEVICE not in target._read_all_start_timers
    assert DEVICE not in target._read_all_active
    target.on_config_read.assert_not_called()
    with patch("grobro.ha.client.Timer"):
        target._Client__on_message(target._client, None, request)
        queued = list(target._config_read_queues[DEVICE])
        expected = [r.growatt.register_no for r in model.get_known_registers(DEVICE).config_registers.values()]
        assert queued == expected
        target._Client__kickoff_next_config_read(DEVICE)
    target.on_config_read.assert_called_once_with(DEVICE, expected[0])


@pytest.mark.parametrize("stage", ["kickoff", "response"])
def test_cancelled_config_timer_cannot_affect_restarted_read_all(clients, stage):
    target, _ = clients
    request = message(f"homeassistant/button/grobro/{DEVICE}/read_all/press", b"")
    with patch("grobro.ha.client.Timer.start"):
        if stage == "kickoff":
            target._Client__on_message(target._client, None, request)
            previous = target._read_all_start_timers[DEVICE]
        else:
            target._read_all_active.add(DEVICE)
            target._config_read_queues[DEVICE] = deque([4, 5])
            target._Client__kickoff_next_config_read(DEVICE)
            previous = target._config_read_timers[DEVICE]
        target._Client__reset_config_read_state()
        if stage == "kickoff":
            target._Client__on_message(target._client, None, request)
            current = target._read_all_start_timers[DEVICE]
        else:
            target._read_all_active.add(DEVICE)
            target._config_read_queues[DEVICE] = deque([4, 5])
            target._Client__kickoff_next_config_read(DEVICE)
            current = target._config_read_timers[DEVICE]
        queued = list(target._config_read_queues[DEVICE])
        sent = target.on_config_read.call_count
        # Replay a callback that entered before cancellation and waited for
        # the runtime lock until after HA recovery installed a new sequence.
        previous.function(*previous.args, **previous.kwargs)
        assert target.on_config_read.call_count == sent
        assert list(target._config_read_queues[DEVICE]) == queued
        timers = target._read_all_start_timers if stage == "kickoff" else target._config_read_timers
        assert timers[DEVICE] is current
        current.function(*current.args, **current.kwargs)
        assert target.on_config_read.call_count == sent + 1


@pytest.mark.parametrize("service", ["neo", "clock"])
def test_replaced_runtime_timer_cannot_execute_or_replace_current_timer(clients, service):
    from grobro.ha.neo_power_runtime import schedule_known_neo_state_probe
    from grobro.ha.time_sync_runtime import schedule_next_time_sync
    target, _ = clients
    if service == "neo":
        schedule = schedule_known_neo_state_probe
        attribute = "_neo_startup_probe_timer"
        callback = "grobro.ha.neo_power_runtime.request_known_neo_states"
    else:
        schedule = schedule_next_time_sync
        attribute = "_time_sync_timer"
        callback = "grobro.ha.time_sync_runtime.sync_supported_clocks"
    with patch("threading.Timer.start"), patch(callback) as work:
        schedule(target)
        previous = getattr(target, attribute)
        schedule(target)
        current = getattr(target, attribute)
        previous.function(*previous.args, **previous.kwargs)
        work.assert_not_called()
        assert getattr(target, attribute) is current
        current.function(*current.args, **current.kwargs)
        work.assert_called_once_with(target)


@pytest.mark.parametrize("kind", ["device", "automatic", "manual", "detected", "observe"])
def test_deeply_nested_persistence_is_recoverable(tmp_path, monkeypatch, kind):
    from grobro.ha import battery_position as batteries
    monkeypatch.chdir(tmp_path)
    names = {"device": "config_TEST.json", "automatic": "battery_positions.json",
             "manual": "battery_manual_positions.json", "detected": "battery_detected.json",
             "observe": "battery_detected.json"}
    path = tmp_path / names[kind]
    path.write_text("[" * 20000 + "0" + "]" * 20000, encoding="utf-8")
    if kind == "device":
        assert model.DeviceConfig.from_file(str(path)) is None
        model.DeviceConfig(serial_number="TEST").to_file(str(path))
        assert model.DeviceConfig.from_file(str(path)).serial_number == "TEST"
    elif kind == "observe":
        client = SimpleNamespace()
        batteries.observe_battery_serials(client, "0PVPTEST", {"bat2_ser_part_1": "SN00200000000001"})
        assert json.loads(path.read_text())["0PVPTEST"] == [
            {"physical_slot": 2, "serial": "SN00200000000001"},
        ]
    else:
        loader = {"automatic": batteries._load_all_positions,
                  "manual": batteries._load_manual_positions,
                  "detected": batteries._load_detected_serials}[kind]
        assert loader() == {}


@pytest.mark.parametrize("failure", ["construct", "start"])
@pytest.mark.parametrize("error", [RuntimeError, OSError])
def test_ingress_thread_failure_closes_bound_server_socket(failure, error):
    from grobro.ha import battery_ingress as ingress
    server = ingress.BoundedIngressServer(("127.0.0.1", 0), ingress.BatteryIngressHandler)
    target = "threading.Thread" if failure == "construct" else "threading.Thread.start"
    try:
        with patch.object(ingress, "BoundedIngressServer", return_value=server), patch(target, side_effect=error("threads unavailable")):
            with pytest.raises(error):
                ingress.start_battery_ingress_server(0)
        assert server.socket.fileno() == -1
    finally:
        server.server_close()


@pytest.mark.parametrize("side", ["ha", "source"])
def test_rejected_primary_mqtt_loop_start_aborts_and_cleans_both_clients(clients, side):
    import paho.mqtt.client as mqtt
    from grobro.ha_bridge import run_clients
    target, source = clients
    failing = target if side == "ha" else source
    failing._client.loop_start.return_value = mqtt.MQTT_ERR_INVAL
    signals = MagicMock()
    with patch("grobro.ha.neo_power_runtime.schedule_known_neo_state_probe"), patch("grobro.ha.time_sync_runtime.schedule_next_time_sync"):
        with pytest.raises(RuntimeError, match="MQTT"):
            run_clients(target, source, signals)
    signals.wait.assert_not_called()
    target._client.disconnect.assert_called_once()
    source._client.disconnect.assert_called_once()
    assert target._stopped
    assert source._forward_stopped
