import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from paho.mqtt.client import MQTTMessage

from grobro.grobro.client import Client, get_property, dump_message_binary
import grobro.grobro.client as grobro_client
from grobro.model.mqtt_config import MQTTConfig


DATA_DIR = __file__[: __file__.rfind("/")] + "/model/data"


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
            instance.connect.assert_called_once_with("h", 1883, 60)

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


    def test_forward_client_waits_for_connack_before_use(self, client):
        forward = MagicMock()

        def complete_connect():
            reason = MagicMock()
            reason.is_failure = False
            forward.on_connect(forward, None, None, reason, None)

        forward.loop_start.side_effect = complete_connect

        with patch("grobro.grobro.client.mqtt.Client", return_value=forward):
            connected = client._Client__connect_to_growatt_server(
                "QMN000ABC1D2E3FG"
            )

        assert connected is forward
        forward.connect.assert_called_once_with("forward.com", 7006, 60)
        forward.subscribe.assert_called_once_with("+/QMN000ABC1D2E3FG")
        assert client._forward_ready[
            "forward_client_QMN000ABC1D2E3FG"
        ].is_set()

    def test_forward_client_queues_until_connack(self, client):
        forward = MagicMock()
        forward.publish.return_value = (0, MagicMock())

        with patch("grobro.grobro.client.mqtt.Client", return_value=forward):
            connected = client._Client__connect_to_growatt_server(
                "QMN000ABC1D2E3FG"
            )
            client._Client__publish_to_growatt_server(
                "QMN000ABC1D2E3FG",
                "c/33/QMN000ABC1D2E3FG",
                b"payload",
                0,
                False,
            )

        assert connected is forward
        forward.publish.assert_not_called()
        key = "forward_client_QMN000ABC1D2E3FG"
        assert len(client._forward_pending[key]) == 1

        reason = MagicMock()
        reason.is_failure = False
        forward.on_connect(forward, None, None, reason, None)

        forward.subscribe.assert_called_once_with("+/QMN000ABC1D2E3FG")
        forward.publish.assert_called_once()
        assert key not in client._forward_pending

    def test_forward_publish_no_conn_is_queued_and_flushed_after_reconnect(self, client):
        forward = MagicMock()
        forward.publish.side_effect = [(grobro_client.mqtt.MQTT_ERR_NO_CONN, None), (0, None)]

        with patch("grobro.grobro.client.mqtt.Client", return_value=forward):
            client._Client__connect_to_growatt_server("QMN000ABC1D2E3FG")

        reason = MagicMock()
        reason.is_failure = False
        forward.on_connect(forward, None, None, reason, None)

        client._Client__publish_to_growatt_server(
            "QMN000ABC1D2E3FG",
            "c/33/QMN000ABC1D2E3FG",
            b"payload",
            0,
            False,
        )

        key = "forward_client_QMN000ABC1D2E3FG"
        assert not client._forward_ready[key].is_set()
        assert len(client._forward_pending[key]) == 1

        forward.on_connect(forward, None, None, reason, None)

        assert client._forward_ready[key].is_set()
        assert key not in client._forward_pending
        assert forward.publish.call_count == 2


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
        assert "Received compound config response" in caplog.text
        assert "NEO QMN000BZP4N991ML -> Better GroBro: config response" not in caplog.text

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

    def test_noah_heater_is_added_directly_to_input_state(self, client):
        data = (Path(DATA_DIR) / "NoahReadInputRegisters_0-124.bin").read_bytes()
        msg = _msg("c/33/0PVP0000TEST0001", data)

        with patch(
            "grobro.grobro.client.heater_state_from_unscrambled",
            return_value="1&2 On",
        ) as heater_decoder:
            client._client.on_message(None, None, msg)

        heater_decoder.assert_called_once()
        state = client.on_input_register.call_args.args[0]
        assert state.payload["heater"] == "1&2 On"

    @patch("grobro.grobro.client._cloud_lower", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD", "true")
    @patch("grobro.grobro.client.GROWATT_CLOUD_ENABLED", True)
    def test_growatt_cloud_forwarding(self, client):
        client._forward_clients = {}
        with patch.object(client, "_Client__publish_to_growatt_server") as mock_publish:
            data = (Path(DATA_DIR) / "NeoConfigTLV_340.bin").read_bytes()
            msg = _msg("c/33/QMN000ABC1D2E3FG", data)
            client._client.on_message(None, None, msg)
            mock_publish.assert_called_once_with(
                "QMN000ABC1D2E3FG",
                "c/33/QMN000ABC1D2E3FG",
                msg.payload,
                msg.qos,
                msg.retain,
            )

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
        with patch.object(client, "_Client__publish_to_growatt_server") as mock_publish:
            data = (Path(DATA_DIR) / "NeoConfigWriteAck_DataInterval.bin").read_bytes()
            msg = _msg("c/33/QMN000ABC1D2E3FG", data)
            client._client.on_message(None, None, msg)
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
        with patch.object(
            client, "_Client__publish_to_growatt_server", side_effect=Exception("boom")
        ):
            data = (Path(DATA_DIR) / "NeoConfigTLV_340.bin").read_bytes()
            msg = _msg("c/33/QMN000ABC1D2E3FG", data)
            client._client.on_message(None, None, msg)
            client.on_config.assert_called_once()


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

            def complete_connect():
                reason = MagicMock()
                reason.is_failure = False
                fc.on_connect(fc, None, None, reason, None)

            fc.loop_start.side_effect = complete_connect

            result = client._Client__connect_to_growatt_server("test-dev")
            assert result is fc
            fc.connect.assert_called_once()
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


    def test_forward_queue_overflow_drops_oldest_once_with_warning(self, client, caplog):
        caplog.set_level("WARNING", logger=grobro_client.LOG.name)
        key = "forward_client_QMN000ABC1D2E3FG"
        for index in range(101):
            client._Client__queue_growatt_forward(
                "QMN000ABC1D2E3FG",
                "c/33/QMN000ABC1D2E3FG",
                str(index).encode(),
                0,
                False,
            )

        queue = client._forward_pending[key]
        assert len(queue) == 100
        assert queue[0][1] == b"1"
        assert queue[-1][1] == b"100"
        assert key in client._forward_overflow_warned
        assert sum(
            "Growatt Cloud connection is delayed" in record.message
            for record in caplog.records
        ) == 1



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
