import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from paho.mqtt.client import MQTTMessage

from grobro.grobro.client import Client, get_property, dump_message_binary
import grobro.grobro.client as grobro_client
from grobro.model.mqtt_config import MQTTConfig


DATA_DIR = Path(__file__).parent / "model" / "data"


@pytest.fixture
def mock_mqtt():
    with patch("grobro.grobro.client.mqtt.Client") as mock_cls:
        instance = MagicMock()
        instance.publish.return_value = (0, MagicMock())
        mock_cls.return_value = instance
        yield instance


@pytest.fixture
def client(mock_mqtt):
    cfg = MQTTConfig(host="localhost", port=1883)
    forward = MQTTConfig(host="forward.com", port=7006)
    c = Client(cfg, forward)
    c.on_config = MagicMock()
    c.on_input_register = MagicMock()
    c.on_holding_register_input = MagicMock()
    c.on_config_read_response = MagicMock()
    return c


def _msg(topic: str, payload: bytes, properties=None):
    m = MagicMock(spec=MQTTMessage)
    m.topic = topic
    m.payload = payload
    m.qos = 0
    m.retain = False
    m.properties.json.return_value = {"UserProperty": properties or []}
    return m


class TestModule:
    def test_get_property_found(self):
        msg = _msg("c/foo", b"")
        result = get_property(msg, "forwarded-for")
        assert result is None

    def test_get_property_missing(self):
        msg = _msg("c/foo", b"", [("other", "val")])
        result = get_property(msg, "forwarded-for")
        assert result is None

    def test_dump_message_binary_uses_central_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("grobro.grobro.client.DUMP_DIR", tmp):
                dump_message_binary("s/33/test", b"hello")

                dump_file = Path(tmp) / "messages.jsonl"
                record = json.loads(dump_file.read_text(encoding="utf-8").strip())
                assert record["topic"] == "s/33/test"
                assert record["payload_length"] == 5

    def test_dump_message_binary_error(self):
        with patch("grobro.grobro.raw_dump.os.makedirs", side_effect=OSError("denied")):
            dump_message_binary("s/33/test", b"data")

    def test_dump_message_binary_write_error(self):
        with patch("builtins.open", side_effect=OSError("denied")):
            dump_message_binary("s/33/test", b"data")

    def test_growatt_cloud_disabled_by_default(self):
        assert grobro_client.GROWATT_CLOUD_ENABLED is False
        assert grobro_client.GROWATT_CLOUD_FILTER == set()


class TestClientLifecycle:
    def test_init_plain(self):
        cfg = MQTTConfig(host="h", port=1883)
        with patch("grobro.grobro.client.mqtt.Client") as mc:
            instance = MagicMock()
            mc.return_value = instance
            c = Client(cfg, cfg)
            assert c._client is instance
            instance.connect_async.assert_called_once_with("h", 1883, 60)
            instance.connect.assert_not_called()

    def test_init_with_auth_tls(self):
        cfg = MQTTConfig(host="h", port=8883, username="u", password="p", use_tls=True)
        with patch("grobro.grobro.client.mqtt.Client") as mc:
            instance = MagicMock()
            mc.return_value = instance
            Client(cfg, cfg)
            instance.username_pw_set.assert_called_once_with("u", "p")
            instance.tls_set.assert_called_once()
            instance.tls_insecure_set.assert_called_once_with(True)

    def test_start_stop(self, client):
        client.start()
        client._client.loop_start.assert_called_once()
        client.stop()
        client._client.loop_stop.assert_called_once()
        client._client.disconnect.assert_called_once()

    def test_stop_with_forward_clients(self, client):
        fc = MagicMock()
        client._forward_clients["fw1"] = fc
        client.stop()
        fc.loop_stop.assert_called_once()
        fc.disconnect.assert_called_once()
        assert client._forward_clients == {}

    def test_on_connect(self, client):
        client._smart_meter_state_cache["dev"] = "{\"power\":1}"
        client._client.on_connect(client._client, None, None, 0, None)
        client._client.subscribe.assert_called_once_with("c/#")
        assert client._smart_meter_state_cache == {}


    def test_source_subscribe_local_rejection_keeps_reads_disabled(self, client, caplog):
        client._client.subscribe.return_value = (grobro_client.mqtt.MQTT_ERR_NO_CONN, None)
        client._config_read_ready.clear()
        with caplog.at_level("ERROR"):
            client._client.on_connect(client._client, None, None, 0, None)
        assert not client._config_read_ready.is_set()
        assert "rejected c/# subscription locally" in caplog.text

    def test_source_subscribe_exception_keeps_reads_disabled(self, client, caplog):
        client._client.subscribe.side_effect = OSError("broker temporarily unavailable")
        client._config_read_ready.clear()
        with caplog.at_level("ERROR"):
            client._client.on_connect(client._client, None, None, 0, None)
        assert not client._config_read_ready.is_set()
        assert "Could not subscribe to Growatt MQTT c/#" in caplog.text

    def test_forward_client_uses_upstream_connection_sequence(self, client):
        forward = MagicMock()
        with patch("grobro.grobro.client.mqtt.Client", return_value=forward) as factory:
            connected = client._Client__connect_to_growatt_server("QMNTEST")
        assert connected is forward
        factory.assert_called_once_with(client_id="QMNTEST", callback_api_version=grobro_client.mqtt.CallbackAPIVersion.VERSION2)
        assert [call[0] for call in forward.mock_calls] == [
            "tls_set", "tls_insecure_set", "connect", "subscribe", "loop_start",
        ]
        forward.connect.assert_called_once_with("forward.com", 7006, 60)
        forward.subscribe.assert_called_once_with("+/QMNTEST")
        forward.tls_set.assert_called_once_with(cert_reqs=grobro_client.ssl.CERT_NONE)
        forward.tls_insecure_set.assert_called_once_with(True)
        forward.connect_async.assert_not_called()
        forward.reconnect_delay_set.assert_not_called()
        assert forward.on_message == client._Client__on_message_forward_client


    def test_forward_client_publishes_live_packet_directly(self, client):
        forward = MagicMock()
        with patch("grobro.grobro.client.mqtt.Client", return_value=forward):
            client._Client__publish_to_growatt_server("QMNTEST", "c/33/QMNTEST", b"payload", 2, True)
        forward.publish.assert_called_once_with("c/33/QMNTEST", payload=b"payload", qos=2, retain=True)
        assert not hasattr(client, "_forward_pending")


    @pytest.mark.parametrize("qos", [0, 1, 2])
    def test_forward_publish_no_conn_does_not_replay_old_packet(self, client, qos):
        forward = MagicMock()
        forward.publish.side_effect = [(grobro_client.mqtt.MQTT_ERR_NO_CONN, None), (0, None)]
        with patch("grobro.grobro.client.mqtt.Client", return_value=forward):
            client._Client__publish_to_growatt_server("QMNTEST", "topic", b"old", qos, False)
            client._Client__publish_to_growatt_server("QMNTEST", "topic", b"new", qos, False)
        assert [call.kwargs["payload"] for call in forward.publish.call_args_list] == [b"old", b"new"]
        assert not hasattr(client, "_forward_pending")



class TestClientSend:
    def test_send_command(self, client):
        from grobro.model.modbus_function import GrowattModbusFunctionSingle
        cmd = GrowattModbusFunctionSingle(
            device_id="QMN000ABC1D2E3FG",
            function=3,
            register=100,
            value=100,
        )
        client.send_command(cmd)
        client._client.publish.assert_called_once()
        args = client._client.publish.call_args
        assert args[0][0] == "s/33/QMN000ABC1D2E3FG"
        assert len(args[0][1]) > 0

    def test_send_config_read_message(self, client, caplog):
        caplog.set_level("INFO", logger=grobro_client.LOG.name)
        client.send_config_read_message("QMN000ABC1D2E3FG", 1280)
        client._client.publish.assert_called_once()
        topic = client._client.publish.call_args[0][0]
        assert topic == "s/33/QMN000ABC1D2E3FG"
        assert (
            "Better GroBro -> NEO QMN000ABC1D2E3FG: request config \"Unknown setting\" (register 1280)"
            in caplog.text
        )

    def test_send_config_message(self, client):
        client.send_config_message("QMN000ABC1D2E3FG", 1280, "60")
        client._client.publish.assert_called_once()
        topic = client._client.publish.call_args[0][0]
        assert topic == "s/33/QMN000ABC1D2E3FG"

    def test_send_command_failure(self, client):
        client._client.publish.return_value = (1, None)
        from grobro.model.modbus_function import GrowattModbusFunctionSingle
        cmd = GrowattModbusFunctionSingle(
            device_id="QMN000ABC1D2E3FG", function=3, register=100, value=100
        )
        client.send_command(cmd)


class TestClientOnMessage:
    def test_forwarded_message_skipped(self, client):
        msg = _msg("c/test", b"data", [("forwarded-for", "ha")])
        client._client.on_message(None, None, msg)
        assert not client._client.publish.called

    def test_config_message_neo_340(self, client):
        data = (Path(DATA_DIR) / "NeoConfigTLV_340.bin").read_bytes()
        msg = _msg("c/33/QMN000ABC1D2E3FG", data)
        client._client.on_message(None, None, msg)
        client.on_config.assert_called_once()

    def test_config_message_neo_341(self, client):
        data = (Path(DATA_DIR) / "NeoConfigTLV_341.bin").read_bytes()
        msg = _msg("c/33/QMN000ABC1D2E3FG", data)
        client._client.on_message(None, None, msg)
        client.on_config.assert_called_once()

    @pytest.mark.parametrize("device_id", [
        "QMN000ABC1D2E3FG", "0PVP000ABC123", "0HVR000ABC123",
    ])
    def test_tlv_config_updates_shared_interval_and_wifi_states(self, client, device_id):
        from grobro.model.device_config import DeviceConfig

        config = DeviceConfig(serial_number=device_id, data_interval="10", wifi_signal="-61")
        wire = _msg(f"c/33/{device_id}", b"wire")
        # Full TLV packets (340) must update HA state but never complete a
        # pending single-register config read.
        with patch("grobro.grobro.client.parser.unscramble",
                   return_value=bytes.fromhex("00 01 00 07 01 54 00 00")), patch(
            "grobro.grobro.client.parser.find_config_offset", return_value=0
        ), patch("grobro.grobro.client.parser.parse_config_type", return_value=config):
            client._client.on_message(None, None, wire)

        published = {
            call.args[0]: call.args[1]
            for call in client._client.publish.call_args_list
            if len(call.args) > 1
        }
        assert published[f"homeassistant/config/grobro/{device_id}/4/get"] == 10
        assert published[f"homeassistant/config/grobro/{device_id}/76/get"] == -61
        client.on_config_read_response.assert_not_called()

    @pytest.mark.parametrize("device_id", [
        "QMN000ABC1D2E3FG", "0PVP000ABC123", "0HVR000ABC123",
    ])
    def test_invalid_tlv_measurements_are_not_merged_into_metadata(self, client, device_id):
        from grobro.model.device_config import DeviceConfig

        incoming = DeviceConfig(
            serial_number=device_id, data_interval="1280",
            wifi_signal="0", sw_version="7.7.1",
        )
        wire = _msg(f"c/33/{device_id}", b"wire")
        with patch("grobro.grobro.client.parser.unscramble",
                   return_value=bytes.fromhex("00 01 00 07 01 54 00 00")), patch(
            "grobro.grobro.client.parser.find_config_offset", return_value=0,
        ), patch("grobro.grobro.client.parser.parse_config_type", return_value=incoming):
            client._client.on_message(None, None, wire)
        client.on_config.assert_called_once()
        _, clean = client.on_config.call_args.args
        assert clean.data_interval is None
        assert clean.wifi_signal is None
        assert clean.sw_version == "7.7.1"
        # The raw parsed object remains unchanged, and neither invalid state
        # is presented as an updated HA sensor/number.
        assert incoming.data_interval == "1280"
        assert incoming.wifi_signal == "0"
        published = [call.args[0] for call in client._client.publish.call_args_list]
        assert f"homeassistant/config/grobro/{device_id}/4/get" not in published
        assert f"homeassistant/config/grobro/{device_id}/76/get" not in published

    def test_partial_tlv_does_not_erase_existing_valid_measurement(self, client):
        from grobro.model.device_config import DeviceConfig
        from grobro.ha.config_runtime import _merge_config

        previous = DeviceConfig(data_interval="5", wifi_signal="-61")
        incoming = DeviceConfig(data_interval="1280", wifi_signal="0")
        cleaned = client._sanitize_tlv_config_measurements("QMN000ABC1D2E3FG", incoming)
        merged = _merge_config(previous, cleaned)
        assert merged.data_interval == "5"
        assert merged.wifi_signal == "-61"

    def test_wifi_source_is_logged_for_tlv_and_direct_read(self, client, caplog):
        from grobro.model.device_config import DeviceConfig

        caplog.set_level("INFO", logger=grobro_client.LOG.name)
        client._publish_tlv_config_states(
            "QMN000ABC1D2E3FG", DeviceConfig(wifi_signal="-61"),
        )
        client._publish_config_state(
            "QMN000ABC1D2E3FG", 76, -62,
            retain=True, source="register response",
        )
        assert "Wi-Fi signal -61 dBm received via device configuration telegram" in caplog.text
        assert "Wi-Fi signal -62 dBm received via register response" in caplog.text

    def test_missing_mqtt_publish_status_does_not_claim_acceptance(self, client, caplog):
        caplog.set_level("INFO", logger=grobro_client.LOG.name)
        # An HA runtime shutdown guard returns None without publishing.
        client.on_config_register_value = MagicMock(return_value=None)
        client._publish_config_state(
            "QMN000ABC1D2E3FG", 76, -61,
            retain=True, source="register response",
        )
        assert "Wi-Fi signal -61 dBm received via register response" in caplog.text
        assert "HA MQTT publish not confirmed" in caplog.text
        assert "HA MQTT publish accepted" not in caplog.text

    def test_rejected_wifi_publish_does_not_claim_acceptance(self, client, caplog):
        client.on_config_register_value = MagicMock(return_value=(4, None))
        client._publish_config_state(
            "QMN000ABC1D2E3FG", 76, -61,
            retain=True, source="register response",
        )
        assert "MQTT rejected Home Assistant config state" in caplog.text
        assert "Wi-Fi signal -61 dBm received via register response" not in caplog.text

    @pytest.mark.parametrize(("interval", "wifi"), [
        ("1280", "-61"), ("garbage", "-61"), ("10", "0"),
        ("10", "not-a-number"), (None, None),
    ])
    def test_tlv_config_rejects_invalid_or_missing_state_values(self, client, interval, wifi):
        from grobro.model.device_config import DeviceConfig

        client._publish_tlv_config_states(
            "QMN000ABC1D2E3FG",
            DeviceConfig(data_interval=interval, wifi_signal=wifi),
        )
        published_topics = [call.args[0] for call in client._client.publish.call_args_list]
        if interval not in ("10",):
            assert "homeassistant/config/grobro/QMN000ABC1D2E3FG/4/get" not in published_topics
        if wifi not in ("-61",):
            assert "homeassistant/config/grobro/QMN000ABC1D2E3FG/76/get" not in published_topics

    def test_tlv_does_not_publish_sensitive_or_network_configuration(self, client):
        from grobro.model.device_config import DeviceConfig

        client._publish_tlv_config_states(
            "0PVP000ABC123",
            DeviceConfig(
                data_interval="5", wifi_signal="-72",
                password="SECRET", remote_ip="192.0.2.1",
                remote_url="example.invalid", remote_port="7006",
            ),
        )
        topics = [call.args[0] for call in client._client.publish.call_args_list]
        assert topics == [
            "homeassistant/config/grobro/0PVP000ABC123/4/get",
            "homeassistant/config/grobro/0PVP000ABC123/76/get",
        ]

    @pytest.mark.parametrize("device_id", [
        "QMN000ABC1D2E3FG", "0PVP000ABC123", "0HVR000ABC123",
    ])
    def test_config_state_validates_interval_and_wifi_uniformly(self, client, device_id):
        client._publish_config_state(device_id, 4, "1280", retain=True)
        client._publish_config_state(device_id, 76, "0", retain=True)
        client._publish_config_state(device_id, 4, "5", retain=True)
        client._publish_config_state(device_id, 76, "-61", retain=True)
        values = [(call.args[0], call.args[1]) for call in client._client.publish.call_args_list]
        assert values == [
            (f"homeassistant/config/grobro/{device_id}/4/get", 5),
            (f"homeassistant/config/grobro/{device_id}/76/get", -61),
        ]

    @pytest.mark.parametrize("device_id", [
        "QMN000ABC1D2E3FG", "0PVP000ABC123", "0HVR000ABC123",
    ])
    def test_invalid_config_read_does_not_update_metadata(self, client, device_id):
        wire = _msg(f"c/33/{device_id}", b"wire")
        parsed = {
            "device_id": device_id, "register_no": 4, "value": "1280",
            "entries": [
                {"register_no": 4, "value": "1280"},
                {"register_no": 76, "value": "0"},
                {"register_no": 76, "value": "-62"},
            ],
        }
        with patch("grobro.grobro.client.parser.unscramble",
                   return_value=bytes.fromhex("00 01 00 07 00 00 01 19")), patch(
            "grobro.grobro.client.parser.parse_config_message", return_value=parsed,
        ):
            client._client.on_message(None, None, wire)
        client.on_config.assert_called_once()
        _, config = client.on_config.call_args.args
        assert config.wifi_signal == "-62"
        assert config.data_interval is None
        topics = [call.args[0] for call in client._client.publish.call_args_list]
        assert f"homeassistant/config/grobro/{device_id}/4/get" not in topics
        assert f"homeassistant/config/grobro/{device_id}/76/get" in topics

    def test_config_state_publish_rejection_is_logged(self, client, caplog):
        client.on_config_register_value = MagicMock(return_value=(4, None))
        client._publish_config_state("QMN000ABC1D2E3FG", 76, -61, retain=True)
        client.on_config_register_value.assert_called_once_with(
            "QMN000ABC1D2E3FG", 76, -61, retain=True,
        )
        assert "MQTT rejected Home Assistant config state" in caplog.text

    def test_invalid_compound_config_number_does_not_hide_next_wifi_value(self, client):
        # A bad R4 must not terminate a compound R76 response.
        wire = _msg("c/33/QMN000BZP4N991ML", b"wire")
        parsed = {
            "device_id": "QMN000BZP4N991ML",
            "register_no": 4,
            "value": "broken",
            "entries": [
                {"register_no": 4, "value": "broken"},
                {"register_no": 76, "value": "-61"},
            ],
        }
        with patch("grobro.grobro.client.parser.unscramble",
                   return_value=bytes.fromhex("00 01 00 07 00 00 01 19")), patch(
            "grobro.grobro.client.parser.parse_config_message", return_value=parsed,
        ):
            client._client.on_message(None, None, wire)
        topics = {call.args[0]: call.args[1] for call in client._client.publish.call_args_list
                  if len(call.args) > 1}
        assert "homeassistant/config/grobro/QMN000BZP4N991ML/4/get" not in topics
        assert topics["homeassistant/config/grobro/QMN000BZP4N991ML/76/get"] == -61
        client.on_config_read_response.assert_called_once_with("QMN000BZP4N991ML", 76)

    def test_compound_config_read_fixture_publishes_individual_registers(self, client):
        data = (Path(DATA_DIR) / "NeoConfigReadResponse_337.bin").read_bytes()
        msg = _msg("c/33/QMN000ABC1D2E3FG", data)
        client._client.on_message(None, None, msg)

        topics = [
            call.args[0]
            for call in client._client.publish.call_args_list
            if call.args
        ]
        assert "homeassistant/config/grobro/QMN000ABC1D2E3FG/4/get" in topics
        assert "homeassistant/config/grobro/QMN000ABC1D2E3FG/5/get" in topics
        assert client.on_config_read_response.call_count > 1

    def test_compound_neo_config_read_publishes_each_tlv(self, client, caplog):
        data = bytes.fromhex(
            "00 01 00 07 00 30 01 19 "
            "51 4d 4e 30 30 30 42 5a 50 34 4e 39 39 31 4d 4c "
            "00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
            "00 02 00 "
            "00 4c 00 04 2d 30 36 31 "
            "00 05 00 01 31 "
            "44 58"
        )
        msg = _msg("c/33/QMN000BZP4N991ML", b"wire")
        caplog.set_level("DEBUG", logger=grobro_client.LOG.name)

        with patch("grobro.grobro.client.parser.unscramble", return_value=data):
            client._client.on_message(None, None, msg)

        publishes = {
            call.args[0]: call.args[1]
            for call in client._client.publish.call_args_list
            if len(call.args) >= 2
        }
        assert publishes[
            "homeassistant/config/grobro/QMN000BZP4N991ML/76/get"
        ] == -61
        assert publishes[
            "homeassistant/config/grobro/QMN000BZP4N991ML/5/get"
        ] == "1"
        assert client.on_config_read_response.call_count == 2
        client.on_config_read_response.assert_any_call("QMN000BZP4N991ML", 76)
        client.on_config_read_response.assert_any_call("QMN000BZP4N991ML", 5)
        assert "Wi-Fi signal -61 dBm received via compound config telegram" in caplog.text
        assert "Wi-Fi signal -61 dBm received via single-register response" not in caplog.text
        assert "Received compound config response" in caplog.text
        assert "NEO QMN000BZP4N991ML -> Better GroBro: config response" not in caplog.text

    def test_single_wifi_reply_uses_single_register_source(self, client, caplog):
        wire = _msg("c/33/QMN000BZP4N991ML", b"wire")
        parsed = {
            "device_id": "QMN000BZP4N991ML",
            "register_no": 76,
            "value": "-59",
            "entries": [{"register_no": 76, "value": "-59"}],
        }
        caplog.set_level("INFO", logger=grobro_client.LOG.name)
        with patch("grobro.grobro.client.parser.unscramble",
                   return_value=bytes.fromhex("00 01 00 07 00 00 01 19")), patch(
            "grobro.grobro.client.parser.parse_config_message", return_value=parsed,
        ):
            client._client.on_message(None, None, wire)
        assert "Wi-Fi signal -59 dBm received via single-register response" in caplog.text
        assert "received via compound config telegram" not in caplog.text

    def test_config_software_version_response_updates_metadata(self, client, caplog):
        data = bytes.fromhex(
            "00 01 00 07 00 2b 01 19 "
            "51 4d 4e 30 30 30 41 42 43 31 44 32 45 33 46 47 "
            "00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
            "00 01 00 "
            "00 15 00 05 31 2e 32 2e 33 "
            "00 00"
        )
        msg = _msg("c/33/QMN000ABC1D2E3FG", b"wire")
        caplog.set_level("INFO", logger=grobro_client.LOG.name)

        with patch("grobro.grobro.client.REGISTER_CAPTURE_ENABLED", False):
            with patch("grobro.grobro.client.parser.unscramble", return_value=data):
                with patch.object(client, "send_config_read_message") as config_read:
                    client._client.on_message(None, None, msg)

        config_read.assert_not_called()
        client.on_config.assert_called_once()
        device_id, version_config = client.on_config.call_args.args
        assert device_id == "QMN000ABC1D2E3FG"
        assert version_config.sw_version == "1.2.3"
        assert version_config.hw_version is None

    def test_config_hardware_version_response_updates_metadata(self, client):
        data = bytes.fromhex(
            "00 01 00 07 00 2b 01 19 "
            "51 4d 4e 30 30 30 41 42 43 31 44 32 45 33 46 47 "
            "00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
            "00 01 00 "
            "00 16 00 04 56 31 2e 30 "
            "00 00"
        )
        msg = _msg("c/33/QMN000ABC1D2E3FG", b"wire")

        with patch("grobro.grobro.client.parser.unscramble", return_value=data):
            client._client.on_message(None, None, msg)

        client.on_config.assert_called_once()
        device_id, version_config = client.on_config.call_args.args
        assert device_id == "QMN000ABC1D2E3FG"
        assert version_config.sw_version is None
        assert version_config.hw_version == "V1.0"

    def test_version_metadata_mapping_uses_config_name_not_device_family(
        self, client
    ):
        from types import SimpleNamespace

        register = SimpleNamespace(
            growatt=SimpleNamespace(
                register_no=21,
                data=SimpleNamespace(data_type="STRING"),
            )
        )
        known = SimpleNamespace(config_registers={"software_version": register})
        data = bytes.fromhex(
            "00 01 00 07 00 2e 01 19 "
            "48 41 51 30 30 30 41 42 43 31 44 32 45 33 46 47 "
            "00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
            "00 01 00 "
            "00 15 00 07 33 2e 38 2e 32 2e 38 "
            "00 00"
        )
        msg = _msg("c/33/HAQ000ABC1D2E3FG", b"wire")

        with patch(
            "grobro.grobro.client._known_registers_for_device",
            return_value=known,
        ):
            with patch("grobro.grobro.client.parser.unscramble", return_value=data):
                client._client.on_message(None, None, msg)

        client.on_config.assert_called_once()
        device_id, metadata = client.on_config.call_args.args
        assert device_id == "HAQ000ABC1D2E3FG"
        assert metadata.sw_version == "3.8.2.8"

    def test_config_write_ack_280(self, client):
        data = (Path(DATA_DIR) / "NeoConfigWriteAck_DataInterval.bin").read_bytes()
        msg = _msg("c/33/QMN000ABC1D2E3FG", data)
        client._client.on_message(None, None, msg)

    def test_config_readback_uses_internal_key_not_display_name(self):
        from grobro.grobro.client import _config_register_key, _config_register_name

        assert _config_register_name("QMN000ABC1D2E3FG", 4) == "Update Interval"
        assert _config_register_key("QMN000ABC1D2E3FG", 4) == "data_interval"
        assert _config_register_key("0PVP0000TEST0001", 4) == "data_interval"
        assert _config_register_key("0HVR0000TEST0001", 30) == "time_zone"

    @pytest.mark.parametrize(("device_id", "register_no"), [
        ("QMN000ABC1D2E3FG", 4),
        ("0PVP0000TEST0001", 4),
        ("0HVR0000TEST0001", 4),
        ("0HVR0000TEST0001", 30),
    ])
    def test_accepted_config_write_schedules_readback_without_ack(self, client, device_id, register_no):
        with patch("grobro.grobro.client.threading.Timer") as timer_factory:
            client.send_config_message(device_id, register_no, "2")
            timer_factory.assert_called_once()
            callback = timer_factory.call_args.args[1]
            timer_factory.return_value.start.assert_called_once()
            with patch.object(client, "send_config_read_message", return_value=(0, None)) as read:
                callback()
            read.assert_called_once_with(device_id, register_no)

    @pytest.mark.parametrize("register_no", [17, 18, 19, 31, 32, 76])
    def test_config_write_does_not_probe_unsafe_registers(self, client, register_no):
        with patch("grobro.grobro.client.threading.Timer") as timer_factory:
            client.send_config_message("QMN000ABC1D2E3FG", register_no, "1")
            timer_factory.assert_not_called()

    def test_failed_config_write_does_not_schedule_readback(self, client):
        client._client.publish.return_value = (4, None)
        with patch("grobro.grobro.client.threading.Timer") as timer_factory:
            client.send_config_message("QMN000ABC1D2E3FG", 4, "10")
            timer_factory.assert_not_called()

    def test_new_config_write_cancels_previous_readback(self, client):
        with patch("grobro.grobro.client.threading.Timer") as timer_factory:
            client.send_config_message("QMN000ABC1D2E3FG", 4, "5")
            first = timer_factory.return_value
            client.send_config_message("QMN000ABC1D2E3FG", 4, "10")
            first.cancel.assert_called_once()

    def test_config_ack_does_not_duplicate_deferred_readback(self, client):
        device_id = "QMN000ABC1D2E3FG"
        with patch("grobro.grobro.client.threading.Timer"):
            client.send_config_message(device_id, 4, "10")
            msg = _msg(f"c/33/{device_id}", b"wire")
            with patch("grobro.grobro.client.parser.unscramble", return_value=bytes.fromhex("00 01 00 07 00 00 01 18")), patch(
                "grobro.grobro.client.parser.parse_config_ack",
                return_value={"device_id": device_id, "register_no": 4},
            ), patch.object(client, "send_config_read_message") as read:
                client._client.on_message(None, None, msg)
            read.assert_not_called()

    def test_config_write_ack_uses_pending_write_for_human_readable_label(
        self, client, caplog
    ):
        device_id = "0PVP0000TEST0001"
        caplog.set_level("INFO", logger=grobro_client.LOG.name)

        client.send_config_message(device_id, 31, "2026-10-02 00:00:00")
        assert list(client._pending_config_writes[device_id]) == [31]

        ack = b"\x00\x01\x00\x07\x00\x00\x01\x18"
        msg = _msg(f"c/33/{device_id}", b"wire")
        with patch("grobro.grobro.client.parser.unscramble", return_value=ack):
            with patch(
                "grobro.grobro.client.parser.parse_config_ack",
                return_value={
                    "device_id": device_id,
                    "register_no": 465,
                },
            ):
                client._client.on_message(None, None, msg)

        assert (
            'NOAH 0PVP0000TEST0001 -> Better GroBro: setting accepted for '
            '"System Time" (register 31)'
            in caplog.text
        )
        assert "register 465" not in caplog.text
        assert device_id not in client._pending_config_writes

    def test_unknown_config_register_has_human_readable_fallback(self):
        assert (
            grobro_client._config_register_label("0PVP0000TEST0001", 465)
            == '"Unknown setting" (register 465)'
        )

    def test_truncated_modbus_block_warning_includes_safe_packet_context(self, caplog):
        import struct
        from grobro.model.modbus_message import GrowattModbusMessage

        # "BZP4" deliberately mimics bytes from a device identifier where
        # a Modbus register-block header would normally start.
        body = b"BZP4" + bytes(543)
        header = struct.pack(">HHHBB30s", 1, 7, 30 + len(body), 1, 3,
                             b"SECRET_DEVICE_SERIAL".ljust(30, b"\\0"))
        raw = header + body
        assert len(raw) == 585
        with caplog.at_level("WARNING"):
            assert GrowattModbusMessage.parse_grobro(raw) is None
        assert "Truncated register block 16986..20532" in caplog.text
        assert "message_type=0x0103" in caplog.text
        assert "function=3" in caplog.text
        assert "packet_bytes=585" in caplog.text
        assert "block_offset=38" in caplog.text
        assert "SECRET_DEVICE_SERIAL" not in caplog.text
        assert "425A5034" not in caplog.text

    def test_valid_modbus_fixture_has_no_truncated_block_warning(self, caplog):
        from grobro.grobro.parser import unscramble
        from grobro.model.modbus_message import GrowattModbusMessage

        raw = unscramble((Path(DATA_DIR) / "NeoReadInputRegisters.bin").read_bytes())
        with caplog.at_level("WARNING"):
            parsed = GrowattModbusMessage.parse_grobro(raw)
        assert parsed is not None
        assert "Truncated register block" not in caplog.text

    def test_modbus_input_register_neo(self, client):
        data = (Path(DATA_DIR) / "NeoReadInputRegisters.bin").read_bytes()
        msg = _msg("c/33/QMN000ABC1D2E3FG", data)
        client._client.on_message(None, None, msg)
        client.on_input_register.assert_called_once()

    def test_neo_version_config_registers_are_known_but_hidden(self):
        registers = grobro_client._known_registers_for_device("QMN000ABC1D2E3FG")
        software = registers.config_registers["software_version"]
        hardware = registers.config_registers["hardware_version"]

        assert software.growatt.register_no == 21
        assert hardware.growatt.register_no == 22
        assert software.homeassistant.publish is False
        assert hardware.homeassistant.publish is False
        assert (
            grobro_client._config_register_label("QMN000ABC1D2E3FG", 21)
            == '"Software Version" (register 21)'
        )
        assert (
            grobro_client._config_register_label("QMN000ABC1D2E3FG", 22)
            == '"Hardware Version" (register 22)'
        )

    def test_modbus_single_register_neo(self, client):
        data = (Path(DATA_DIR) / "NeoReadSingleRegister_3.bin").read_bytes()
        msg = _msg("c/33/QMN000ABC1D2E3FG", data)
        client._client.on_message(None, None, msg)
        client.on_holding_register_input.assert_called_once()

    def test_modbus_prese_single_noah(self, client):
        data = (Path(DATA_DIR) / "NoahPresetSingle_OutputLimit.bin").read_bytes()
        msg = _msg("c/33/0PVP0000TEST0001", data)
        client._client.on_message(None, None, msg)

    def test_modbus_input_noah(self, client):
        data = (Path(DATA_DIR) / "NoahReadInputRegisters_0-124.bin").read_bytes()
        msg = _msg("c/33/0PVP0000TEST0001", data)
        client._client.on_message(None, None, msg)
        client.on_input_register.assert_called_once()

    @pytest.mark.parametrize("raw_state, expected", list(enumerate([
        "Off", "1 On", "2 On", "1&2 On", "3 On", "1&3 On", "2&3 On",
        "1&2&3 On", "4 On", "1&4 On", "2&4 On", "1&2&4 On", "3&4 On",
        "1&3&4 On", "2&3&4 On", "All On",
    ])))
    def test_noah_heater_from_generic_input_register(self, client, raw_state, expected):
        from grobro.grobro import parser
        from grobro.model.growatt_registers import KNOWN_NOAH_REGISTERS
        from grobro.model.modbus_message import (
            HEADER_SIZE, METADATA_SIZE, GrowattModbusFunction, GrowattModbusMessage,
        )

        data = (DATA_DIR / "NoahReadInputRegisters_0-124.bin").read_bytes()
        plain = bytearray(parser.unscramble(data))
        message = GrowattModbusMessage.parse_grobro(plain)
        assert message.function == GrowattModbusFunction.READ_INPUT_REGISTER
        register = KNOWN_NOAH_REGISTERS.input_registers["heater"]
        assert register.growatt.position.register_no == 17
        assert register.growatt.position.offset == 0
        assert register.growatt.position.size == 2
        assert register.growatt.data.data_type == "ENUM"
        block = next(block for block in message.register_blocks if block.start <= 17 <= block.end)
        values = bytearray(block.values)
        offset = (17 - block.start) * 2
        values[offset:offset + 2] = raw_state.to_bytes(2, "big")
        block.values = bytes(values)
        assert register.growatt.data.parse(message.get_data(register.growatt.position)) == expected

        block_offset = HEADER_SIZE + METADATA_SIZE
        for preceding in message.register_blocks:
            if preceding is block:
                break
            block_offset += preceding.size()
        plain[block_offset:block_offset + block.size()] = block.build_grobro()
        msg = _msg("c/33/0PVP0000TEST0001", parser.unscramble(bytes(plain)))
        client._client.on_message(None, None, msg)

        client.on_input_register.assert_called_once()
        state = client.on_input_register.call_args.args[0]
        assert state.payload["heater"] == expected

    @patch("grobro.grobro.client._cloud_lower", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD_ENABLED", True)
    def test_growatt_cloud_forwarding(self, client):
        client._forward_clients = {}
        with patch.object(client._cloud_queue, "_sender") as mock_publish:
            data = (Path(DATA_DIR) / "NeoConfigTLV_340.bin").read_bytes()
            msg = _msg("c/33/QMN000ABC1D2E3FG", data)
            client._client.on_message(None, None, msg)
            from time import monotonic, sleep
            deadline = monotonic() + 2
            while mock_publish.call_count < 1 and monotonic() < deadline:
                sleep(0.01)
            mock_publish.assert_called_once_with(
                "QMN000ABC1D2E3FG",
                "c/33/QMN000ABC1D2E3FG",
                msg.payload,
                msg.qos,
                msg.retain,
                received_at=pytest.approx(monotonic(), abs=2),
            )

    def test_neo_non_write_message_is_parsed_only_once(self, client):
        # Regression: NEO function-4 data previously called generic parser
        # twice, duplicating a single malformed register-block warning.
        msg = _msg("c/33/QMN000ABC1D2E3FG", b"wire")
        decoded = bytes.fromhex("00 01 00 07 00 00 01 04") + b"\x00" * 80
        with patch("grobro.grobro.client.parser.unscramble", return_value=decoded), patch(
            "grobro.grobro.client.GrowattModbusMessage.parse_grobro", return_value=None,
        ) as parse:
            client._client.on_message(None, None, msg)
        parse.assert_called_once_with(decoded)

    def test_neo_single_register_write_still_uses_ack_path(self, client):
        from grobro.model.modbus_message import (
            GrowattModbusMessage, GrowattModbusFunction, GrowattModbusWriteAck,
        )
        msg = _msg("c/33/QMN000ABC1D2E3FG", b"wire")
        decoded = bytes.fromhex("00 01 00 07 00 00 01 06") + b"\x00" * 80
        ack_message = GrowattModbusMessage(
            unknown=1, device_id="QMN000ABC1D2E3FG",
            function=GrowattModbusFunction.PRESET_SINGLE_REGISTER,
            register_blocks=[],
            write_ack=GrowattModbusWriteAck(register_no=0, status=0, value=1),
        )
        with patch("grobro.grobro.client.parser.unscramble", return_value=decoded), patch(
            "grobro.grobro.client.GrowattModbusMessage.parse_grobro", return_value=ack_message,
        ) as parse:
            client._client.on_message(None, None, msg)
        parse.assert_called_once_with(decoded)

    def test_neo_type0103_suffix_serial_skips_generic_modbus(self, client):
        """Captured NEO packets may embed only 'BZP4N991ML' at offset 38."""
        import struct
        device_id = "QMN000BZP4N991ML"
        serial = device_id.encode("ascii").ljust(30, b"\x00")
        embedded = b"BZP4N991ML".ljust(16, b"\x00")
        decoded = (
            struct.pack(">HHHBB30s", 1, 7, 577, 1, 3, serial)
            + embedded + bytes(585 - 38 - 16)
        )
        msg = _msg(f"c/33/{device_id}", b"wire")
        with patch("grobro.grobro.client.parser.unscramble", return_value=decoded), patch(
            "grobro.grobro.client.GrowattModbusMessage.parse_grobro"
        ) as generic_parser:
            client._client.on_message(None, None, msg)
        generic_parser.assert_not_called()

    def test_neo_type0103_other_serial_does_not_skip_generic_modbus(self, client):
        """Only a suffix of the same verified serial is handled specially."""
        import struct
        device_id = "QMN000BZP4N991ML"
        serial = device_id.encode("ascii").ljust(30, b"\x00")
        decoded = (
            struct.pack(">HHHBB30s", 1, 7, 577, 1, 3, serial)
            + b"UNRELATED1".ljust(16, b"\x00") + bytes(585 - 38 - 16)
        )
        msg = _msg(f"c/33/{device_id}", b"wire")
        with patch("grobro.grobro.client.parser.unscramble", return_value=decoded), patch(
            "grobro.grobro.client.GrowattModbusMessage.parse_grobro", return_value=None,
        ) as generic_parser:
            client._client.on_message(None, None, msg)
        generic_parser.assert_called_once_with(decoded)

    def test_noah_type0103(self, client):
        data = (Path(DATA_DIR) / "NoahType0103_HoldingRegs.bin").read_bytes()
        msg = _msg("c/33/0PVP0000TEST0001", data)
        with patch(
            "grobro.grobro.client.GrowattModbusMessage.parse_grobro"
        ) as generic_parser:
            client._client.on_message(None, None, msg)
        generic_parser.assert_not_called()

    def test_noah_type0110(self, client):
        data = (Path(DATA_DIR) / "NoahType0110_PresetMResp.bin").read_bytes()
        msg = _msg("c/33/0PVP0000TEST0001", data)
        client._client.on_message(None, None, msg)

    def test_noah_type0125(self, client):
        data = (Path(DATA_DIR) / "NoahType0125_SerialResp.bin").read_bytes()
        msg = _msg("c/33/0PVP0000TEST0001", data)
        client._client.on_message(None, None, msg)

    def test_noah_type_fe19_config(self, client, caplog):
        caplog.set_level("INFO", logger=grobro_client.LOG.name)
        data = (Path(DATA_DIR) / "NoahTypeFE19_Config.bin").read_bytes()
        msg = _msg("c/33/0PVP0000TEST0001", data)
        client._client.on_message(None, None, msg)
        client.on_config.assert_called_once()
        assert (
            "NOAH 0PVP0000TEST0001 -> Better GroBro: device settings received"
            in caplog.text
        )

    def test_noah_type_fe19_config2(self, client):
        data = (Path(DATA_DIR) / "NoahTypeFE19_Config2.bin").read_bytes()
        msg = _msg("c/33/0PVP0000TEST0001", data)
        client._client.on_message(None, None, msg)
        client.on_config.assert_called_once()

    def test_noah_type_fe19_config3(self, client):
        data = (Path(DATA_DIR) / "NoahTypeFE19_Config3.bin").read_bytes()
        msg = _msg("c/33/0PVP0000TEST0001", data)
        client._client.on_message(None, None, msg)
        client.on_config.assert_called_once()

    def test_noah_type_fe19_devstatus(self, client):
        data = (Path(DATA_DIR) / "NoahTypeFE19_DevStatus.bin").read_bytes()
        msg = _msg("c/33/0PVP0000TEST0001", data)
        client._client.on_message(None, None, msg)

    def test_noah_type_fe25(self, client):
        data = (Path(DATA_DIR) / "NoahTypeFE25_Empty.bin").read_bytes()
        msg = _msg("c/33/0PVP0000TEST0001", data)
        client._client.on_message(None, None, msg)

    def test_identical_smart_meter_state_is_published_once(self, client):
        fake_packet = b"\x00\x00\x00\x00\x00\x00\x6f\x64"
        smart_meter = {
            "message_type": 0x6F64,
            "device_id": "0PVP0000TEST0001",
            "data": '{"power":123}',
        }
        msg = _msg("c/33/0PVP0000TEST0001", b"raw")

        with patch("grobro.grobro.client.parser.unscramble", return_value=fake_packet):
            with patch(
                "grobro.grobro.client.parser.parse_noah_6f64",
                return_value=smart_meter,
            ):
                client._client.on_message(None, None, msg)
                first_count = client._client.publish.call_count
                client._client.on_message(None, None, msg)

        assert first_count == 1
        assert client._client.publish.call_count == first_count


    def test_shinewelink_fe19_fullconfig(self, client):
        data = (Path(DATA_DIR) / "ShineWeLinkFE19_FullConfig.bin").read_bytes()
        msg = _msg("c/33/RAQ0E8H042", data)
        client._client.on_message(None, None, msg)
        client.on_config.assert_not_called()

    def test_shinewelink_config_0129(self, client):
        data = (Path(DATA_DIR) / "ShineWeLinkConfigDump.bin").read_bytes()
        msg = _msg("c/33/RAQ0TEST01", data)
        client._client.on_message(None, None, msg)
        assert client.on_config.call_count == 2
        raq_call, ptq_call = client.on_config.call_args_list
        assert raq_call[0][0] == "RAQ0TEST01"
        assert ptq_call[0][0].startswith("PTQ")

    def test_gateway_wifi_uses_derived_config_callback_when_available(self, client):
        client.on_derived_config = MagicMock()
        client._ptq_for_raq["RAQTEST"] = "PTQTEST"
        data = b"\x00" * 6 + b"\x01\x19" + b"\x00" * 32
        with patch("grobro.grobro.client.parser.unscramble", return_value=data), patch(
            "grobro.grobro.client.parser.parse_config_message",
            return_value={"device_id": "RAQTEST", "register_no": 76, "value": "-61"},
        ):
            client._client.on_message(None, None, _msg("c/33/RAQTEST", b"wire"))
        client.on_config.assert_called_once()
        assert client.on_config.call_args.args[0] == "RAQTEST"
        client.on_derived_config.assert_called_once()
        derived_id, derived_config = client.on_derived_config.call_args.args
        assert derived_id == "PTQTEST"
        assert derived_config.wifi_signal == "-61"

    def test_gateway_wifi_readback_updates_mapped_inverter_without_redirecting_reads(self, client):
        client._ptq_for_raq["RAQTEST"] = "PTQTEST"
        client.send_config_read_message("RAQTEST", 76)
        assert client._client.publish.call_args.args[0] == "s/33/RAQTEST"
        data = b"\x00" * 6 + b"\x01\x19" + b"\x00" * 32
        with patch("grobro.grobro.client.parser.unscramble", return_value=data), patch(
            "grobro.grobro.client.parser.parse_config_message",
            return_value={"device_id": "RAQTEST", "register_no": 76, "value": "-61"},
        ):
            client._client.on_message(None, None, _msg("c/33/RAQTEST", b"wire"))
        configs = {call.args[0]: call.args[1] for call in client.on_config.call_args_list}
        assert configs["RAQTEST"].wifi_signal == "-61"
        assert configs["PTQTEST"].wifi_signal == "-61"
        client.on_config_read_response.assert_called_once_with("RAQTEST", 76)

    def test_topic_sanitization_normal(self, client):
        data = (Path(DATA_DIR) / "NeoConfigTLV_340.bin").read_bytes()
        msg = _msg("c/33/QMN000ABC1D2E3FG", data)
        client._client.on_message(None, None, msg)
        client.on_config.assert_called_once()
        dev_id, _ = client.on_config.call_args[0]
        assert dev_id == "QMN000ABC1D2E3FG"

    def test_topic_sanitization_control_chars(self, client):
        data = (Path(DATA_DIR) / "NeoConfigTLV_340.bin").read_bytes()
        msg = _msg("c/33/QMN000ABC1D2E3FG\x10", data)
        client._client.on_message(None, None, msg)
        client.on_config.assert_called_once()
        dev_id, _ = client.on_config.call_args[0]
        assert "\x10" not in dev_id
        assert dev_id == "QMN000ABC1D2E3FG"

    def test_shinewelink_fe19_devstatus(self, client):
        data = (Path(DATA_DIR) / "ShineWeLinkFE19_DevStatus1.bin").read_bytes()
        msg = _msg("c/33/RAQ0E8H042", data)
        client._client.on_message(None, None, msg)
        client.on_config.assert_not_called()

    def test_shinewelink_fe19_devstatus2(self, client):
        data = (Path(DATA_DIR) / "ShineWeLinkFE19_DevStatus2.bin").read_bytes()
        msg = _msg("c/33/RAQ0E8H042", data)
        client._client.on_message(None, None, msg)
        client.on_config.assert_not_called()

    def test_shinewelink_input_register(self, client):
        data = (Path(DATA_DIR) / "ShineWeLinkReadInputRegisters.bin").read_bytes()
        msg = _msg("c/33/RAQ0E8H042", data)
        client._client.on_message(None, None, msg)
        client.on_input_register.assert_called_once()

    def test_shinewelink_holding_register(self, client):
        data = (Path(DATA_DIR) / "ShineWeLinkReadHoldingRegisters.bin").read_bytes()
        msg = _msg("c/33/RAQ0E8H042", data)
        client._client.on_message(None, None, msg)

    def test_shinewelink_fe25_keepalive(self, client):
        data = (Path(DATA_DIR) / "ShineWeLinkFE25_Keepalive.bin").read_bytes()
        msg = _msg("c/33/RAQ0E8H042", data)
        client._client.on_message(None, None, msg)

    def test_dump_messages_in_on_message(self, client):
        with patch("grobro.grobro.client.DUMP_MESSAGES", True):
            with patch("grobro.grobro.client.dump_message_binary") as mock_dump:
                data = (Path(DATA_DIR) / "NeoConfigTLV_340.bin").read_bytes()
                msg = _msg("c/33/QMN000ABC1D2E3FG", data)
                client._client.on_message(None, None, msg)
                mock_dump.assert_called_once()

    def test_unknown_device_type_modbus(self, client):
        data = (Path(DATA_DIR) / "NeoReadInputRegisters.bin").read_bytes()
        msg = _msg("c/33/UNKN00000000001", data)
        client._client.on_message(None, None, msg)
        client.on_input_register.assert_not_called()

    def test_neo_fixture_is_not_treated_as_nexa_telemetry(self, client):
        data = (Path(DATA_DIR) / "NeoReadInputRegisters.bin").read_bytes()
        msg = _msg("c/33/0HVR000TEST0001", data)
        client._client.on_message(None, None, msg)
        client.on_input_register.assert_not_called()

    def test_neo_fixture_is_not_treated_as_spf_telemetry(self, client):
        data = (Path(DATA_DIR) / "NeoReadInputRegisters.bin").read_bytes()
        msg = _msg("c/33/HAQ000TEST0001", data)
        client._client.on_message(None, None, msg)
        client.on_input_register.assert_not_called()

    def test_invalid_payload_processing(self, client):
        msg = _msg("c/33/QMN000ABC1D2E3FG", b"garbage")
        client._client.on_message(None, None, msg)


class TestClientCloudConfig:
    @patch("grobro.grobro.client._cloud_lower", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD_ENABLED", True)
    @patch("grobro.grobro.client.GROWATT_CLOUD_FILTER", set())
    @patch("grobro.grobro.client.GROWATT_CLOUD_CONFIG_FILTER", "true")
    def test_config_filter_does_not_block_device_to_cloud(self, client):
        with patch.object(client._cloud_queue, "_sender") as mock_publish:
            data = (Path(DATA_DIR) / "NeoConfigWriteAck_DataInterval.bin").read_bytes()
            msg = _msg("c/33/QMN000ABC1D2E3FG", data)
            client._client.on_message(None, None, msg)
            from time import monotonic, sleep
            deadline = monotonic() + 2
            while mock_publish.call_count < 1 and monotonic() < deadline:
                sleep(0.01)
            mock_publish.assert_called_once()

    @patch("grobro.grobro.client._cloud_lower", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD_ENABLED", True)
    @patch("grobro.grobro.client.GROWATT_CLOUD_FILTER", set())
    @patch("grobro.grobro.client.GROWATT_CLOUD_CONFIG_FILTER", "true")
    def test_config_filter_blocks_cloud_to_device_0110(self, client):
        data = (Path(DATA_DIR) / "NoahType0110_PresetMResp.bin").read_bytes()
        msg = _msg("s/0PVP0000TEST0001", data)
        client._Client__on_message_forward_client(None, None, msg)
        client._client.publish.assert_not_called()

    @patch("grobro.grobro.client._cloud_lower", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD_ENABLED", True)
    @patch("grobro.grobro.client.GROWATT_CLOUD_FILTER", set())
    def test_cloud_forwarding_exception(self, client):
        from threading import Event

        failed = Event()

        def fail_cloud(*_args, **_kwargs):
            failed.set()
            raise RuntimeError("Cloud temporarily unavailable")

        with patch.object(client._cloud_queue, "_sender", side_effect=fail_cloud):
            data = (Path(DATA_DIR) / "NeoConfigTLV_340.bin").read_bytes()
            msg = _msg("c/33/QMN000ABC1D2E3FG", data)
            client._client.on_message(None, None, msg)
            # The local parsing path must succeed regardless of Cloud failure.
            client.on_config.assert_called_once()
            assert failed.wait(1), "queued Cloud worker did not execute"


class TestClientForward:
    @patch("grobro.grobro.client._cloud_lower", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD_ENABLED", True)
    def test_cloud_config_read_logs_requested_register(self, client, caplog):
        caplog.set_level("INFO", logger=grobro_client.LOG.name)
        from grobro.grobro.builder import build_config_read_packet

        payload = build_config_read_packet("QMN000ABC1D2E3FG", 76)
        client._Client__on_message_forward_client(
            None,
            None,
            _msg("s/QMN000ABC1D2E3FG", payload),
        )

        assert any(
            "Growatt Cloud -> NEO QMN000ABC1D2E3FG: request config \"Wi-Fi Signal Strength\" (register 76)"
            in record.message
            for record in caplog.records
        )

    @patch("grobro.grobro.client._cloud_lower", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD_ENABLED", True)
    def test_forward_client_message(self, client):
        data = (Path(DATA_DIR) / "NeoConfigTLV_340.bin").read_bytes()
        client._Client__on_message_forward_client(
            None,
            None,
            _msg("s/QMN000ABC1D2E3FG", data, [("forwarded-for", "growatt")]),
        )
        client._client.publish.assert_called_once()

    def test_connect_to_growatt_server(self, client):
        with patch("grobro.grobro.client.mqtt.Client") as mc:
            fc = MagicMock()
            mc.return_value = fc

            result = client._Client__connect_to_growatt_server("test-dev")
            assert result is fc
            fc.connect.assert_called_once_with("forward.com", 7006, 60)
            fc.subscribe.assert_called_once_with("+/test-dev")
            fc.loop_start.assert_called_once()

            result2 = client._Client__connect_to_growatt_server("test-dev")
            assert result2 is fc
            assert mc.call_count == 1

    def test_forward_client_dump_messages(self, client):
        with patch("grobro.grobro.client.DUMP_MESSAGES", True):
            with patch("grobro.grobro.client.dump_message_binary") as mock_dump:
                client._Client__on_message_forward_client(
                    None,
                    None,
                    _msg("s/device1", b"data"),
                )
                mock_dump.assert_called_once()

    def test_forward_client_cloud_disabled(self, client):
        with patch("grobro.grobro.client.GROWATT_CLOUD_ENABLED", False):
            client._Client__on_message_forward_client(
                None,
                None,
                _msg("s/device1", b"data"),
            )
            client._client.publish.assert_not_called()

    def test_forward_client_device_not_in_filter(self, client):
        client._Client__on_message_forward_client(
            None,
            None,
            _msg("s/device1", b"data"),
        )
        client._client.publish.assert_not_called()

    @patch("grobro.grobro.client._cloud_lower", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD_ENABLED", True)
    def test_forward_client_publish_exception(self, client):
        data = (Path(DATA_DIR) / "NeoConfigTLV_340.bin").read_bytes()
        with patch.object(client._client, "publish", side_effect=Exception("boom")):
            client._Client__on_message_forward_client(
                None,
                None,
                _msg("s/QMN000ABC1D2E3FG", data),
            )





class TestExtractDeviceId:
    def test_clean_neo_serial(self):
        from grobro.grobro.client import _extract_device_id
        assert _extract_device_id("c/33/QMN000ABC123") == "QMN000ABC123"

    def test_clean_noah_serial(self):
        from grobro.grobro.client import _extract_device_id
        assert _extract_device_id("c/0PVP000ABC123") == "0PVP000ABC123"

    def test_strips_trailing_control_char(self):
        from grobro.grobro.client import _extract_device_id
        assert _extract_device_id("s/33/ZGQ0F5601J\x18") == "ZGQ0F5601J"

    def test_strips_question_mark(self):
        from grobro.grobro.client import _extract_device_id
        assert _extract_device_id("s/33/ZGQ0F5601J?\x18") == "ZGQ0F5601J"

    def test_strips_non_alphanumeric(self):
        from grobro.grobro.client import _extract_device_id
        assert _extract_device_id("c/X/AB-CD_EF.GH") == "ABCDEFGH"


def test_slow_cloud_forward_does_not_block_local_processing(client):
    """Local device parsing and callbacks must finish while Cloud stalls."""
    import threading

    entered_cloud = threading.Event()
    release_cloud = threading.Event()
    data = (DATA_DIR / "NeoConfigTLV_340.bin").read_bytes()
    message = _msg("c/33/QMN000ABC1D2E3FG", data)

    def stalled_cloud(*_args, **_kwargs):
        entered_cloud.set()
        release_cloud.wait(3)

    try:
        with patch("grobro.grobro.client._cloud_lower", "true"), patch(
            "grobro.grobro.client.GROWATT_CLOUD", "true"
        ), patch.object(client._cloud_queue, "_sender", side_effect=stalled_cloud):
            client._client.on_message(None, None, message)
            assert entered_cloud.wait(1), "Cloud work was not scheduled"
            client.on_config.assert_called_once()
    finally:
        release_cloud.set()
        client._cloud_queue.stop()


def test_cloud_forward_queue_bounds_backlog_and_drops_stale_packets():
    import threading
    import time
    from grobro.grobro.cloud_dispatch import (
        CloudForwardQueue, MAX_PENDING_CLOUD_MESSAGES,
    )

    entered = threading.Event()
    release = threading.Event()
    delivered = []

    def sender(*args, **kwargs):
        delivered.append((args, kwargs))
        entered.set()
        release.wait(2)

    queue = CloudForwardQueue(sender)
    try:
        assert queue.submit("QMNTEST", "topic", b"first", 0, False)
        assert entered.wait(1)
        for i in range(MAX_PENDING_CLOUD_MESSAGES):
            assert queue.submit("QMNTEST", "topic", str(i).encode(), 0, False)
        assert not queue.submit("QMNTEST", "topic", b"overflow", 0, False)
        queue.stop()
        release.set()
        time.sleep(0.02)
        assert len(delivered) == 1, "stopped queue must not replay pending messages"
    finally:
        release.set()
        queue.stop()


def test_cloud_shutdown_does_not_wait_for_ongoing_cloud_connect(client):
    import threading
    import time

    started = threading.Event()
    release = threading.Event()
    fake_forward = MagicMock()

    def slow_connect(*_args):
        started.set()
        release.wait(3)

    fake_forward.connect.side_effect = slow_connect
    with patch("grobro.grobro.client.mqtt.Client", return_value=fake_forward):
        worker = threading.Thread(
            target=lambda: client._Client__connect_to_growatt_server("QMNTEST"),
            daemon=True,
        )
        worker.start()
        try:
            assert started.wait(1)
            start = time.monotonic()
            client.stop()
            assert time.monotonic() - start < 1, "shutdown held the Cloud connect lock"
        finally:
            release.set()
            worker.join(timeout=1)


def test_delayed_cloud_connect_discards_expired_queued_packet(client):
    """An expired packet must not be published after a slow Cloud connect."""
    import time

    forward = MagicMock()
    timestamp = time.monotonic() - 20
    with patch.object(
        client, "_Client__connect_to_growatt_server", return_value=forward
    ):
        client._Client__publish_to_growatt_server(
            "QMNTEST", "c/33/QMNTEST", b"stale", 0, False,
            received_at=timestamp,
        )
    forward.publish.assert_not_called()


def test_failed_cloud_connection_has_per_device_retry_cooldown():
    """A broken Cloud broker must not be reconnected for each queued telegram."""
    import threading
    import time
    from grobro.grobro.cloud_dispatch import CloudForwardQueue

    attempted = threading.Event()
    tries = []

    def unavailable(*args, **_kwargs):
        tries.append(args[0])
        attempted.set()
        raise OSError("cloud offline")

    queue = CloudForwardQueue(unavailable)
    try:
        assert queue.submit("QMNTEST", "c/33/QMNTEST", b"first", 0, False)
        assert attempted.wait(1)
        assert queue.submit("QMNTEST", "c/33/QMNTEST", b"second", 0, False)
        time.sleep(0.1)
        assert tries == ["QMNTEST"]
        assert queue.submit("0PVPTEST", "c/33/0PVPTEST", b"third", 0, False)
        deadline = time.monotonic() + 2
        while len(tries) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert tries == ["QMNTEST", "0PVPTEST"]
    finally:
        queue.stop()


def test_queued_cloud_publish_rejection_triggers_retry_failure(client):
    """Paho can reject a queued publish without raising an exception."""
    import time

    forward = MagicMock()
    forward.publish.return_value = (grobro_client.mqtt.MQTT_ERR_NO_CONN, None)
    with patch.object(
        client, "_Client__connect_to_growatt_server", return_value=forward
    ):
        with pytest.raises(ConnectionError, match="rejected locally"):
            client._Client__publish_to_growatt_server(
                "QMNTEST", "c/33/QMNTEST", b"payload", 1, False,
                received_at=time.monotonic(),
            )
    forward.publish.assert_called_once_with(
        "c/33/QMNTEST", payload=b"payload", qos=1, retain=False
    )


def test_cloud_queue_preserves_binary_payload_qos_retain_and_fifo():
    """Cloud forwarding must preserve the existing upstream wire contract."""
    import threading
    import time
    from grobro.grobro.cloud_dispatch import CloudForwardQueue

    received = []
    ready = threading.Event()

    def sender(device, topic, payload, qos, retain, *, received_at):
        received.append((device, topic, payload, qos, retain))
        if len(received) == 3:
            ready.set()

    queue = CloudForwardQueue(sender)
    try:
        packets = [
            ("QMNTEST", "c/33/QMNTEST", b"\x00\x01config", 1, True),
            ("0PVPTEST", "c/33/0PVPTEST", b"\x00\xffbinary", 0, False),
            ("QMNTEST", "c/33/QMNTEST", b"telemetry", 2, False),
        ]
        for packet in packets:
            assert queue.submit(*packet)
        assert ready.wait(2)
        assert received == packets
    finally:
        queue.stop()
