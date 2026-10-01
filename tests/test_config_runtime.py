from grobro.ha.config_runtime import persisted_config_data
from grobro.model.device_config import DeviceConfig


def test_persisted_config_data_ignores_volatile_fe19_values():
    first = DeviceConfig(
        serial_number="0PVP0000TEST0001",
        device_type="61",
        sw_version="4.0.2.6",
        hw_version="1.0",
        mac_address="00:11:22:33:44:55",
        datetime="2026-10-01 17:51:22",
        wifi_signal="-61",
        local_ip="192.168.1.10",
        remote_ip="1.2.3.4",
    )
    second = first.model_copy(
        update={
            "datetime": "2026-10-01 20:00:19",
            "wifi_signal": "-58",
            "local_ip": "192.168.1.11",
            "remote_ip": "5.6.7.8",
        }
    )

    assert persisted_config_data(first) == persisted_config_data(second)


def test_persisted_config_data_detects_real_device_metadata_changes():
    first = DeviceConfig(
        serial_number="0PVP0000TEST0001",
        device_type="61",
        sw_version="4.0.2.6",
        model_id="NOAH",
    )
    second = first.model_copy(update={"sw_version": "4.0.2.7"})

    assert persisted_config_data(first) != persisted_config_data(second)
