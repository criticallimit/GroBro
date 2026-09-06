"""Home Assistant availability and reconnect hook installation."""

from grobro.ha import client as ha_client_module
from grobro.ha.availability import clear_reconnect_caches, publish_availability


def install_availability_runtime() -> None:
    client_cls = ha_client_module.Client
    original_on_connect = client_cls._Client__on_connect

    def on_connect_clean(self, client, userdata, flags, reason_code, properties):
        clear_reconnect_caches(self)
        return original_on_connect(self, client, userdata, flags, reason_code, properties)

    client_cls._Client__on_connect = on_connect_clean

    def publish_availability_clean(self, device_id: str, online: bool):
        return publish_availability(self, device_id, online)

    client_cls._Client__publish_availability = publish_availability_clean
