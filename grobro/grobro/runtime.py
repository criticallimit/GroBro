"""Central bootstrap for Better GroBro's permanent runtime hardening."""

from grobro.grobro.noah_heater_hook import install_noah_heater_hook
from grobro.grobro.raw_dump_hook import install_raw_dump_hook
from grobro.ha.cleanup import install_ha_cleanup_hook
from grobro.ha.performance import install_ha_performance_hook
from grobro.ha.system_time_cleanup import install_system_time_entity_cleanup


def install_runtime_layers() -> None:
    """Install permanent compatibility and performance layers in stable order."""
    install_raw_dump_hook()
    install_noah_heater_hook()
    install_ha_cleanup_hook()
    install_ha_performance_hook()
    install_system_time_entity_cleanup()
