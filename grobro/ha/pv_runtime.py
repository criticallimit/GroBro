"""Home Assistant dynamic-PV family gating."""

from grobro.ha import client as ha_client_module
from grobro.model.device_family import uses_dynamic_pv_count


def install_pv_runtime() -> None:
    client_cls = ha_client_module.Client
    original_detect_pv_count = client_cls._Client__detect_neo_pv_count

    def detect_pv_count_clean(self, device_id: str, payload: dict):
        if not uses_dynamic_pv_count(device_id):
            return None
        return original_detect_pv_count(self, device_id, payload)

    client_cls._Client__detect_neo_pv_count = detect_pv_count_clean
