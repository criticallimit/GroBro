"""Home Assistant client instance-state initialization hook."""

from grobro.ha import client as ha_client_module
from grobro.ha.runtime_state import initialize_instance_state


def install_state_runtime() -> None:
    client_cls = ha_client_module.Client
    original_init = client_cls.__init__

    def init_with_state(self, *args, **kwargs):
        initialize_instance_state(self)
        return original_init(self, *args, **kwargs)

    client_cls.__init__ = init_with_state
